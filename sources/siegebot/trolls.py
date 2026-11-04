"""The real reason this bot exists. Shh."""
import asyncio
import logging
import random
import re
import time

import discord
from discord.ext import commands

from .defaults import TROLL_TYPES
from .util import chance, fill, spongebob

log = logging.getLogger("siegebot.trolls")

PASSIVE = ["react", "mock", "typing", "correct"]
ACTIVE = ["nickname", "ghost_ping", "fake_ban", "voice_shuffle", "voice_mute", "dm_report", "sound_ambush", "noise_blast"]
VOICE_ACTIONS = ("voice_shuffle", "voice_mute", "sound_ambush", "noise_blast")
ACTIONS = {
    "nickname": "Rename", "restore_nick": "Restore nickname", "ghost_ping": "Ghost ping",
    "fake_ban": "Fake ban", "voice_shuffle": "Voice shuffle", "voice_mute": "Voice mute 5s",
    "dm_report": "Fake report DM", "mock_next": "Mock next message",
    "sound_ambush": "Fake cue in their call", "noise_blast": "Noise blast in their call",
}
HIDDEN = {"nick": "nickname", "unnick": "restore_nick", "ghost": "ghost_ping", "fakeban": "fake_ban",
          "shuffle": "voice_shuffle", "mute": "voice_mute", "report": "dm_report", "mock": "mock_next",
          "ambush": "sound_ambush", "blast": "noise_blast"}


class Trolls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.mock_next = set()
        self.loop_task = None

    async def cog_load(self):
        self.loop_task = asyncio.create_task(self.chaos_loop())

    async def cog_unload(self):
        if self.loop_task:
            self.loop_task.cancel()

    def enabled(self):
        return bool(self.db.get("trolls_enabled"))

    def odds(self, target, scale=1.0):
        return float(target["chance"]) * float(self.db.get("chaos")) * scale

    def find_member(self, user_id):
        for g in self.bot.guilds:
            m = g.get_member(int(user_id))
            if m:
                return m
        return None

    @staticmethod
    def sendable_channels(guild):
        me = guild.me
        return [c for c in guild.text_channels if c.permissions_for(me).send_messages and c.permissions_for(me).view_channel]

    # ------------------------------------------------------------------ actions
    async def run_action(self, action, member, channel=None):
        """Perform a troll on a member. Returns a human-readable result string."""
        try:
            fn = getattr(self, f"do_{action}")
        except AttributeError:
            return f"Unknown action {action}"
        self.bot.stealth[member.id] = time.time() + 30  # keep this out of the event log
        try:
            result = await fn(member, channel)
        except discord.HTTPException as e:
            result = f"Discord refused ({e.status}). Check bot role position/permissions."
        self.db.log("troll", f"{action} -> {member}: {result}")
        return result

    async def do_nickname(self, member, channel=None):
        t = self.db.target(member.id)
        if t is None:
            self.db.upsert_target(member.id, label=str(member), trolls=[])
            t = self.db.target(member.id)
        if not t["nick_changed"]:
            self.db.q("UPDATE targets SET original_nick=?, nick_changed=1 WHERE user_id=?", (member.nick, member.id))
        new = random.choice(self.db.get("nicknames"))[:32]
        await member.edit(nick=new, reason="Totally legitimate moderation")
        return f"renamed to '{new}'"

    async def do_restore_nick(self, member, channel=None):
        t = self.db.target(member.id)
        if not t or not t["nick_changed"]:
            return "nothing to restore"
        await member.edit(nick=t["original_nick"])
        self.db.q("UPDATE targets SET nick_changed=0, original_nick=NULL WHERE user_id=?", (member.id,))
        return "nickname restored"

    async def do_ghost_ping(self, member, channel=None):
        chans = self.sendable_channels(member.guild)
        if not chans:
            return "no channel"
        ch = channel or random.choice(chans)
        msg = await ch.send(member.mention)
        await msg.delete()
        return f"ghost pinged in #{ch}"

    async def do_fake_ban(self, member, channel=None):
        ch = channel or member.guild.system_channel or (self.sendable_channels(member.guild) or [None])[0]
        if not ch:
            return "no channel"
        await ch.send(fill(random.choice(self.db.get("fake_ban_lines")), target=member.mention))
        await asyncio.sleep(random.uniform(6, 12))
        await ch.send(random.choice(self.db.get("fake_ban_reveal")))
        return f"fake-banned in #{ch}"

    async def do_voice_shuffle(self, member, channel=None):
        if not member.voice or not member.voice.channel:
            return "not in voice"
        home = member.voice.channel
        others = [c for c in member.guild.voice_channels if c != home and c.permissions_for(member).connect]
        if not others:
            return "no other voice channel"
        await member.move_to(random.choice(others))
        await asyncio.sleep(10)
        if member.voice:  # they may have left already
            await member.move_to(home)
        return "voice shuffled"

    async def do_voice_mute(self, member, channel=None):
        if not member.voice:
            return "not in voice"
        await member.edit(mute=True)
        await asyncio.sleep(5)
        if member.voice:
            await member.edit(mute=False)
        return "muted for 5s"

    async def do_dm_report(self, member, channel=None):
        try:
            await member.send(random.choice(self.db.get("dm_reports")))
        except discord.Forbidden:
            return "their DMs are closed (coward)"
        return "report DM sent"

    async def do_sound_ambush(self, member, channel=None):
        return await self.bot.get_cog("Soundboard").play_at(member, "cue")

    async def do_noise_blast(self, member, channel=None):
        return await self.bot.get_cog("Soundboard").play_at(member, "loud")

    async def do_mock_next(self, member, channel=None):
        self.mock_next.add(member.id)
        return "next message will be mocked"

    async def panic(self):
        """Turn everything off and undo nicknames."""
        self.db.set("trolls_enabled", False)
        restored = 0
        for t in self.db.targets():
            if t["nick_changed"]:
                m = self.find_member(t["user_id"])
                if m and "restored" in await self.run_action("restore_nick", m):
                    restored += 1
        self.db.log("troll", f"PANIC: trolls disabled, {restored} nickname(s) restored")
        return restored

    # ------------------------------------------------------------------ passive
    async def on_target_message(self, message):
        if message.author.id in self.mock_next:
            self.mock_next.discard(message.author.id)
            await message.reply(spongebob(message.content) or "🤡", mention_author=False)
            return
        if not self.enabled():
            return
        t = self.db.target(message.author.id)
        if not t:
            return
        options = [p for p in PASSIVE if p in t["trolls"]]
        if not options or not chance(self.odds(t)):
            return
        kind = random.choice(options)
        try:
            if kind == "react":
                for emoji in random.sample(self.db.get("reactions"), k=min(2, len(self.db.get("reactions")))):
                    await message.add_reaction(emoji)
            elif kind == "mock" and message.content:
                await message.reply(spongebob(message.content), mention_author=False)
            elif kind == "typing":
                async with message.channel.typing():
                    await asyncio.sleep(random.uniform(5, 9))
            elif kind == "correct" and message.content:
                fixed = self.corrupt(message.content)
                if fixed != message.content:
                    await message.reply(f"*{fixed}", mention_author=False)
        except discord.HTTPException:
            pass

    def corrupt(self, text):
        table = {k.lower(): v for k, v in (self.db.get("corrections") or {}).items()}

        def sub(m):
            w = m.group(0)
            return table.get(w.lower(), w)
        return re.sub(r"[A-Za-z']+", sub, text)[:1900]

    # ------------------------------------------------------------------ active loop
    async def chaos_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(max(1, float(self.db.get("troll_loop_minutes"))) * 60)
            if not self.enabled():
                continue
            for t in self.db.targets():
                options = [a for a in ACTIVE if a in t["trolls"]]
                member = self.find_member(t["user_id"])
                if not options or not member or not chance(self.odds(t)):
                    continue
                if not member.voice:
                    options = [o for o in options if o not in VOICE_ACTIONS]
                    if not options:
                        continue
                # the loud ones are rarer
                weights = [0.3 if o in ("fake_ban", "dm_report") else 1.0 for o in options]
                action = random.choices(options, weights=weights)[0]
                asyncio.create_task(self.run_action(action, member))

    # ------------------------------------------------------------------ hidden owner commands
    async def hidden_command(self, message):
        """,,nick @user  ,,ghost @user  ,,fakeban @user  ,,shuffle @user  ,,mute @user  ,,report @user
        ,,mock @user  ,,unnick @user  ,,ambush @user  ,,blast @user
        ,,sound @user <name> [times]   (or ,,sound <name> to play in YOUR channel)  ,,stop  ,,sounds
        ,,target @user  ,,untarget @user  ,,chaos 2  ,,on  ,,off  ,,panic"""
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        parts = message.content[2:].split()
        if not parts:
            return
        cmd = parts[0].lower()
        member = message.mentions[0] if message.mentions else None
        if cmd in HIDDEN and member:
            asyncio.create_task(self.run_action(HIDDEN[cmd], member, channel=message.channel if cmd == "fakeban" else None))
        elif cmd == "sound" and len(parts) > 1:
            board = self.bot.get_cog("Soundboard")
            who = member or message.author
            args = [p for p in parts[1:] if not p.startswith("<@")]
            name = args[0] if args else "loud"
            times = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
            if who.voice and who.voice.channel and board.pick(name):
                self.bot.stealth[who.id] = time.time() + 30
                asyncio.create_task(board.play(who.voice.channel, board.pick(name), times))
        elif cmd == "stop":
            await self.bot.get_cog("Soundboard").stop(message.guild)
        elif cmd == "sounds":
            names = ", ".join(s["name"] for s in self.bot.get_cog("Soundboard").sounds())
            try:
                await message.author.send(f"🔊 Sounds: {names}")
            except discord.HTTPException:
                pass
        elif cmd == "target" and member:
            self.db.upsert_target(member.id, label=str(member), trolls=list(TROLL_TYPES))
            self.db.log("troll", f"{member} added as target via hidden command")
        elif cmd == "untarget" and member:
            await self.run_action("restore_nick", member)
            self.db.q("DELETE FROM targets WHERE user_id=?", (member.id,))
        elif cmd == "chaos" and len(parts) > 1:
            try:
                self.db.set("chaos", max(0.0, min(5.0, float(parts[1]))))
            except ValueError:
                pass
        elif cmd in ("on", "off"):
            self.db.set("trolls_enabled", cmd == "on")
        elif cmd == "panic":
            await self.panic()
        elif cmd == "help":
            try:
                await message.author.send(f"```{self.hidden_command.__doc__}```")
            except discord.HTTPException:
                pass
