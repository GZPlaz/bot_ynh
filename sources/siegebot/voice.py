"""Soundboard: joins a voice channel, plays a sound (loudly), leaves."""
import asyncio
import hashlib
import logging
import os
import random
import shutil
import uuid

import aiohttp
import discord
from discord.ext import commands

from . import sounds

log = logging.getLogger("siegebot.voice")


class Soundboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.data_dir = bot.data_dir
        self.locks = {}
        self.cancel = set()

    def lock(self, guild):
        return self.locks.setdefault(guild.id, asyncio.Lock())

    def sounds(self):
        return sounds.list_sounds(self.data_dir)

    def pick(self, kind):
        """kind: 'cue' (sneaky fake game cues), 'loud' (obnoxious noises) or a sound name."""
        all_s = self.sounds()
        if kind == "cue":
            pool = [s for s in all_s if s["name"].startswith("fake_")]
        elif kind == "loud":
            pool = [s for s in all_s if not s["name"].startswith("fake_")]
        else:
            pool = [s for s in all_s if s["name"] == kind]
        return random.choice(pool) if pool else None

    def source(self, path):
        vol = max(0.0, float(self.db.get("sound_volume")) / 100)
        secs = int(self.db.get("sound_max_seconds") or 20)
        # volume > 1.0 clips and distorts on purpose. That's the point.
        return discord.FFmpegPCMAudio(path, before_options="-nostdin", options=f'-vn -t {secs} -af "volume={vol:.2f}"')

    async def play(self, channel, sound, times=1):
        """Play `sound` (dict from sounds.list_sounds) `times` times in `channel`. Returns a status string."""
        if not os.path.exists(sound["file"]):
            return "sound file missing"
        guild = channel.guild
        async with self.lock(guild):
            self.cancel.discard(guild.id)
            vc = guild.voice_client
            try:
                if vc and vc.channel != channel:
                    await vc.move_to(channel)
                elif not vc:
                    vc = await channel.connect(self_deaf=True, timeout=15)
            except (discord.ClientException, asyncio.TimeoutError, discord.HTTPException) as e:
                return f"couldn't join voice: {e}"
            loop = asyncio.get_running_loop()
            try:
                for _ in range(max(1, min(int(times), 10))):
                    if guild.id in self.cancel:
                        break
                    done = asyncio.Event()
                    vc.play(self.source(sound["file"]), after=lambda e: loop.call_soon_threadsafe(done.set))
                    await done.wait()
                    await asyncio.sleep(0.2)
            except Exception as e:  # ffmpeg/opus missing, etc.
                log.exception("Playback failed")
                return f"playback failed: {e}"
            finally:
                if vc.is_connected():
                    await vc.disconnect(force=True)
        self.db.log("sound", f"Played {sound['name']} ×{times} in {guild.name}/{channel.name}")
        return f"played {sound['name']} in {channel.name}"

    async def play_at(self, member, kind="loud", times=1):
        if not member.voice or not member.voice.channel:
            return "not in voice"
        sound = self.pick(kind)
        if not sound:
            return "no sounds available"
        return await self.play(member.voice.channel, sound, times)

    ROBOT_VOICES = ["en-us", "en-us+m3", "en-us+m7", "en-gb+m2", "en-us+f3", "en-us+croak", "en-gb+whisper",
                    "en-us+klatt", "en-sc+m4", "en-us+f4"]

    def robot_voice(self, user_id=None):
        """Random robot voice, or a fixed one per victim so each friend has 'their' robot voice."""
        if user_id is None:
            return random.choice(self.ROBOT_VOICES), random.randint(165, 200), random.randint(35, 60)
        h = int(hashlib.md5(str(user_id).encode()).hexdigest(), 16)
        return self.ROBOT_VOICES[h % len(self.ROBOT_VOICES)], 150 + h % 60, 20 + (h // 7) % 60

    async def tts(self, text, user_id=None):
        """Render text to a wav with espeak-ng. Returns a sound dict or None."""
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            return None
        d = os.path.join(self.data_dir, "tts")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{uuid.uuid4().hex}.wav")
        voice, speed, pitch = self.robot_voice(user_id)
        proc = await asyncio.create_subprocess_exec(
            exe, "-v", voice, "-s", str(speed), "-p", str(pitch), "-a", "200",
            "-w", path, "--", text[:300], stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        return {"name": "tts", "file": path} if os.path.exists(path) else None

    async def speak(self, channel, text, times=1, user_id=None):
        sound = await self.tts(text, user_id)
        if not sound:
            return "text-to-speech unavailable (install espeak-ng)"
        return await self._play_temp(channel, sound, times, text)

    # ------------------------------------------------------------------ opt-in voice clones
    def clone_ready(self, user_id):
        row = self.db.q("SELECT * FROM voice_clones WHERE user_id=?", (int(user_id),), one=True)
        return row if row and row["sample"] and os.path.exists(row["sample"]) else None

    async def clone_audio(self, user_id, text):
        """Ask the external clone service for `text` in the opted-in user's voice. Returns (sound, error)."""
        row = self.clone_ready(user_id)
        if not row:
            return None, "that person hasn't opted in or uploaded a sample"
        url = (self.db.get("clone_api_url") or "").rstrip("/")
        if not url:
            return None, "voice clone service not configured (panel → Robot Voice & Clones)"
        form = aiohttp.FormData()
        form.add_field("text", text[:400])
        form.add_field("exaggeration", str(self.db.get("clone_exaggeration")))
        with open(row["sample"], "rb") as fh:
            form.add_field("speaker", fh.read(), filename="speaker.wav", content_type="audio/wav")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240)) as http:
                async with http.post(url + "/synthesize", data=form,
                                     headers={"X-Token": self.db.get("clone_api_token") or ""}) as r:
                    if r.status != 200:
                        return None, f"clone service said {r.status}: {(await r.text())[:100]}"
                    audio = await r.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return None, f"clone service unreachable: {e or type(e).__name__}"
        d = os.path.join(self.data_dir, "tts")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{uuid.uuid4().hex}.wav")
        with open(path, "wb") as fh:
            fh.write(audio)
        self.db.q("UPDATE voice_clones SET uses=uses+1 WHERE user_id=?", (int(user_id),))
        self.db.log("clone", f"Generated clone speech for {row['user_name']}: {text[:80]}")
        return {"name": "clone", "file": path}, None

    async def clone_speak(self, channel, user_id, text):
        sound, err = await self.clone_audio(user_id, text)
        if err:
            return err
        return await self._play_temp(channel, sound, 1, text)

    async def _play_temp(self, channel, sound, times, text):
        try:
            return (await self.play(channel, sound, times)).replace(f"played {sound['name']}", f"said '{text[:60]}'")
        finally:
            try:
                os.remove(sound["file"])
            except OSError:
                pass

    async def stop(self, guild):
        self.cancel.add(guild.id)
        vc = guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect(force=True)
