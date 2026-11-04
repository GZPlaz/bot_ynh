"""Soundboard: joins a voice channel, plays a sound (loudly), leaves."""
import asyncio
import logging
import os
import random
import shutil
import uuid

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

    async def tts(self, text):
        """Render text to a wav with espeak-ng. Returns a sound dict or None."""
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            return None
        d = os.path.join(self.data_dir, "tts")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{uuid.uuid4().hex}.wav")
        voice = random.choice(["en-us", "en-us+m3", "en-us+m7", "en-gb+m2", "en-us+f3"])
        proc = await asyncio.create_subprocess_exec(
            exe, "-v", voice, "-s", str(random.randint(165, 200)), "-p", str(random.randint(35, 60)), "-a", "200",
            "-w", path, "--", text[:300], stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        return {"name": "tts", "file": path} if os.path.exists(path) else None

    async def speak(self, channel, text, times=1):
        sound = await self.tts(text)
        if not sound:
            return "text-to-speech unavailable (install espeak-ng)"
        try:
            return (await self.play(channel, sound, times)).replace("played tts", f"said '{text[:60]}'")
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
