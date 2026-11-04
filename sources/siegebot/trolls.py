"""The real reason this bot exists. Shh."""
import asyncio
import logging
import random
import re
import time
from datetime import timedelta

import discord
from discord.ext import commands

from .defaults import TROLL_TYPES
from .util import chance, fill, spongebob

log = logging.getLogger("siegebot.trolls")

PASSIVE = ["react", "mock", "typing", "correct", "parrot", "read_aloud"]
DEATH_RE = re.compile(r"\b(dead|died|i'?m down|rip|my bad|mb|nt|nice try|bruh|ff|gg go next|lag)\b", re.I)
ACTIVE = ["nickname", "ghost_ping", "fake_ban", "voice_shuffle", "voice_mute", "dm_report", "sound_ambush", "noise_blast",
          "micro_timeout", "voice_kick", "role_of_shame", "ping_spree", "parrot",
          "voice_deafen", "voice_stutter", "voice_jail", "fake_callout", "potato_mode", "stat_readout"]
VOICE_ACTIONS = ("voice_shuffle", "voice_mute", "sound_ambush", "noise_blast", "voice_kick",
                 "voice_deafen", "voice_stutter", "voice_jail", "fake_callout", "potato_mode", "stat_readout",
                 "commentator", "join_announcer")
RARE = ("fake_ban", "dm_report", "micro_timeout", "voice_kick", "role_of_shame")
ACTIONS = {
    "nickname": "Rename", "restore_nick": "Restore nickname", "ghost_ping": "Ghost ping",
    "fake_ban": "Fake ban", "voice_shuffle": "Voice shuffle", "voice_mute": "Voice mute 5s",
    "dm_report": "Fake report DM", "mock_next": "Mock next message",
    "sound_ambush": "Fake cue in their call", "noise_blast": "Noise blast in their call",
    "micro_timeout": "Micro timeout (30-90s)", "voice_kick": "Kick from voice", "role_of_shame": "Role of shame",
    "remove_shame": "Remove role of shame", "ping_spree": "Ghost-ping spree", "parrot": "Parrot mode (3 min)",
    "voice_deafen": "Deafen 6s", "voice_stutter": "Mic stutter", "voice_jail": "Voice jail 20s",
    "fake_callout": "Robot fake callout", "potato_mode": "Potato mode (8 kbps, 2 min)",
    "commentator": "Death commentary", "join_announcer": "Robot announcement", "stat_readout": "Read stats aloud",
}
HIDDEN = {"nick": "nickname", "unnick": "restore_nick", "ghost": "ghost_ping", "fakeban": "fake_ban",
          "shuffle": "voice_shuffle", "mute": "voice_mute", "report": "dm_report", "mock": "mock_next",
          "ambush": "sound_ambush", "blast": "noise_blast", "tout": "micro_timeout", "vkick": "voice_kick",
          "shame": "role_of_shame", "unshame": "remove_shame", "spree": "ping_spree", "parrot": "parrot",
          "deafen": "voice_deafen", "stutter": "voice_stutter", "jail": "voice_jail", "callout": "fake_callout",
          "potato": "potato_mode", "dead": "commentator", "announce": "join_announcer", "readstats": "stat_readout"}


class Trolls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.mock_next = set()
        self.loop_task = None
        self.parrots = {}  # user_id -> ts until
        self.sniped = {}  # user_id -> last snipe ts
        self.potato = {}  # voice channel id -> original bitrate
        self.voice_cooldown = {}  # (user_id, kind) -> ts
        self.renaming = set()  # ids the bot is renaming right now (so nick_lock ignores our own edits)

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
        self.renaming.add(member.id)
        try:
            await member.edit(nick=new, reason="Totally legitimate moderation")
        finally:
            asyncio.get_running_loop().call_later(3, self.renaming.discard, member.id)
        return f"renamed to '{new}'"

    async def do_restore_nick(self, member, channel=None):
        t = self.db.target(member.id)
        if not t or not t["nick_changed"]:
            return "nothing to restore"
        self.db.q("UPDATE targets SET nick_changed=0 WHERE user_id=?", (member.id,))  # disarm nick_lock first
        self.renaming.add(member.id)
        try:
            await member.edit(nick=t["original_nick"])
        except discord.HTTPException:
            self.db.q("UPDATE targets SET nick_changed=1 WHERE user_id=?", (member.id,))  # keep the saved original
            raise
        finally:
            asyncio.get_running_loop().call_later(3, self.renaming.discard, member.id)
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

    async def do_micro_timeout(self, member, channel=None):
        secs = random.randint(30, 90)
        reason = random.choice(self.db.get("timeout_reasons"))
        await member.timeout(timedelta(seconds=secs), reason=reason)
        return f"timed out {secs}s: {reason}"

    async def do_voice_kick(self, member, channel=None):
        if not member.voice:
            return "not in voice"
        await member.move_to(None, reason="Connection lost (definitely)")
        return "kicked from voice"

    async def shame_role(self, guild):
        roles = self.db.get("shame_roles") or {}
        role = guild.get_role(int(roles.get(str(guild.id), 0)))
        if not role:
            role = await guild.create_role(name="🤡", colour=discord.Colour(0xFF2D95), hoist=True,
                                           permissions=discord.Permissions.none(), reason="Totally normal role")
            roles[str(guild.id)] = role.id
            self.db.set("shame_roles", roles)
        try:  # as high as the bot can put it, so it's what shows in the member list
            await role.edit(position=max(1, guild.me.top_role.position - 1))
        except discord.HTTPException:
            pass
        return role

    async def do_role_of_shame(self, member, channel=None):
        role = await self.shame_role(member.guild)
        name = random.choice(self.db.get("shame_role_names"))[:100]
        await role.edit(name=name)
        await member.add_roles(role)
        mins = int(self.db.get("shame_minutes") or 30)
        exp = self.db.get("shame_expiry") or {}
        exp[f"{member.guild.id}:{member.id}"] = time.time() + mins * 60
        self.db.set("shame_expiry", exp)
        asyncio.get_running_loop().call_later(mins * 60 + 1, lambda: asyncio.ensure_future(self.expire_shame()))
        return f"wearing '{name}' for {mins} min"

    async def do_remove_shame(self, member, channel=None):
        exp = self.db.get("shame_expiry") or {}
        exp.pop(f"{member.guild.id}:{member.id}", None)
        self.db.set("shame_expiry", exp)
        role = member.guild.get_role(int((self.db.get("shame_roles") or {}).get(str(member.guild.id), 0)))
        if role and role in member.roles:
            await member.remove_roles(role)
            return "role of shame removed"
        return "wasn't wearing it"

    async def expire_shame(self, everything=False):
        exp = self.db.get("shame_expiry") or {}
        for key, until in list(exp.items()):
            if everything or until <= time.time():
                gid, uid = key.split(":")
                guild = self.bot.get_guild(int(gid))
                member = guild.get_member(int(uid)) if guild else None
                if member:
                    self.bot.stealth[member.id] = time.time() + 30
                    try:
                        await self.do_remove_shame(member)
                    except discord.HTTPException:
                        pass
                exp.pop(key, None)
        self.db.set("shame_expiry", exp)

    async def do_ping_spree(self, member, channel=None):
        chans = [c for c in self.sendable_channels(member.guild) if c.permissions_for(member).view_channel]
        chans = random.sample(chans, k=min(5, len(chans)))
        for ch in chans:
            msg = await ch.send(member.mention)
            await msg.delete()
            await asyncio.sleep(random.uniform(2, 6))
        return f"ghost-pinged in {len(chans)} channels"

    async def do_parrot(self, member, channel=None):
        self.parrots[member.id] = time.time() + 180
        return "parrot mode for 3 minutes"

    # nick_lock: they changed it back? new humiliating name.
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick == after.nick or after.id in self.renaming or not self.enabled():
            return
        t = self.db.target(after.id)
        if not t or "nick_lock" not in t["trolls"] or not t["nick_changed"]:
            return
        await asyncio.sleep(random.uniform(1, 4))  # let them enjoy it for a moment
        await self.run_action("nickname", after)

    # typing_sniper: reply before they even hit enter
    @commands.Cog.listener()
    async def on_typing(self, channel, user, when):
        if not getattr(channel, "guild", None) or user.bot or not self.enabled():
            return
        t = self.db.target(user.id)
        if not t or "typing_sniper" not in t["trolls"] or time.time() - self.sniped.get(user.id, 0) < 120:
            return
        if not chance(self.odds(t, 2)):
            return
        self.sniped[user.id] = time.time()
        try:
            await channel.send(fill(random.choice(self.db.get("sniper_lines")), user=user.display_name))
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ voice chat trolls
    async def do_voice_deafen(self, member, channel=None):
        if not member.voice:
            return "not in voice"
        await member.edit(deafen=True)
        try:
            await asyncio.sleep(6)
        finally:
            if member.voice:
                await member.edit(deafen=False)
        return "deafened for 6s"

    async def do_voice_stutter(self, member, channel=None):
        if not member.voice:
            return "not in voice"
        try:
            for _ in range(random.randint(6, 10)):
                await member.edit(mute=True)
                await asyncio.sleep(random.uniform(0.4, 0.9))
                if not member.voice:
                    break
                await member.edit(mute=False)
                await asyncio.sleep(random.uniform(0.3, 0.8))
        finally:
            if member.voice:
                await member.edit(mute=False)  # never leave them muted
        return "mic stuttered"

    async def do_voice_jail(self, member, channel=None):
        if not member.voice or not member.voice.channel:
            return "not in voice"
        home, guild = member.voice.channel, member.guild
        overwrites = {guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
                      guild.me: discord.PermissionOverwrite(connect=True, view_channel=True, move_members=True),
                      member: discord.PermissionOverwrite(view_channel=True, speak=True)}
        jail = await guild.create_voice_channel(random.choice(self.db.get("jail_names"))[:100], category=home.category,
                                                overwrites=overwrites, user_limit=1, reason="Routine maintenance")
        self.bot.suppress_channel_log.add(jail.id)
        try:
            await member.move_to(jail)
            await asyncio.sleep(20)
            if member.voice and member.voice.channel == jail:
                await member.move_to(home)
        finally:
            await jail.delete(reason="Routine maintenance complete")
        return "served 20s in voice jail"

    async def do_fake_callout(self, member, channel=None):
        if not member.voice or not member.voice.channel:
            return "not in voice"
        board = self.bot.get_cog("Soundboard")
        lines = random.sample(self.db.get("fake_callouts"), k=min(2, len(self.db.get("fake_callouts"))))
        return await board.speak(member.voice.channel, " ... ".join(lines))

    async def do_potato_mode(self, member, channel=None):
        if not member.voice or not member.voice.channel:
            return "not in voice"
        ch = member.voice.channel
        if ch.id in self.potato:
            return "already a potato"
        self.potato[ch.id] = ch.bitrate
        await ch.edit(bitrate=8000)
        asyncio.get_running_loop().call_later(120, lambda: asyncio.ensure_future(self.unpotato(ch.id)))
        return f"{ch.name} is now 8 kbps for 2 min"

    # ------------------------------------------------------------------ robot voice chaos
    def cooled(self, user_id, kind, seconds):
        """True if this (user, kind) is off cooldown, and starts the cooldown."""
        if time.time() - self.voice_cooldown.get((user_id, kind), 0) < seconds:
            return False
        self.voice_cooldown[(user_id, kind)] = time.time()
        return True

    async def say_in_call(self, member, text, own_voice=False):
        if not member.voice or not member.voice.channel:
            return "not in voice"
        board = self.bot.get_cog("Soundboard")
        return await board.speak(member.voice.channel, text, user_id=member.id if own_voice else None)

    async def do_commentator(self, member, channel=None):
        line = fill(random.choice(self.db.get("commentator_lines")), user=member.display_name)
        return await self.say_in_call(member, line)

    async def do_join_announcer(self, member, channel=None):
        line = fill(random.choice(self.db.get("announcer_lines")), user=member.display_name)
        return await self.say_in_call(member, line)

    async def do_stat_readout(self, member, channel=None):
        from .fun import fake_stats
        st = fake_stats(self.bot, member)
        text = (f"Attention everyone. Official stat report for {member.display_name}. Rank: {st['rank']}. "
                f"K D: {st['kd']:.2f}. Win rate: {st['wr']:.0f} percent. Headshot percentage: {st['hs']:.0f}. "
                + ("Truly legendary." if st["kd"] > 2 else "Thank you for your attention. Please be kind to them."))
        return await self.say_in_call(member, text)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or not after.channel or before.channel == after.channel or not self.enabled():
            return
        if self.bot.stealth.get(member.id, 0) > time.time():  # we moved them (jail/shuffle), not a real join
            return
        t = self.db.target(member.id)
        if not t or "join_announcer" not in t["trolls"] or not chance(self.odds(t, 4)):
            return
        if self.cooled(member.id, "announce", 300):
            await asyncio.sleep(random.uniform(1.5, 4))
            await self.run_action("join_announcer", member)

    async def unpotato(self, channel_id=None):
        for cid in [channel_id] if channel_id else list(self.potato):
            ch = self.bot.get_channel(cid)
            rate = self.potato.pop(cid, None)
            if ch and rate:
                try:
                    await ch.edit(bitrate=rate)
                except discord.HTTPException:
                    pass

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
        self.parrots.clear()
        self.mock_next.clear()
        await self.unpotato()
        await self.expire_shame(everything=True)
        for gid, rid in (self.db.get("shame_roles") or {}).items():
            guild = self.bot.get_guild(int(gid))
            role = guild.get_role(int(rid)) if guild else None
            if role:
                try:
                    await role.delete(reason="Cleanup")
                except discord.HTTPException:
                    pass
        self.db.set("shame_roles", {})
        for m in [self.find_member(t["user_id"]) for t in self.db.targets()]:
            if m and m.is_timed_out():
                try:
                    await m.timeout(None)
                except discord.HTTPException:
                    pass
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
        if self.parrots.get(message.author.id, 0) > time.time() and message.content:
            try:
                await message.channel.send(message.content[:2000], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
            return
        t = self.db.target(message.author.id)
        if not t:
            return
        in_voice = bool(getattr(message.author, "voice", None) and message.author.voice.channel)
        if in_voice and "commentator" in t["trolls"] and message.content and DEATH_RE.search(message.content) \
                and chance(self.odds(t, 4)) and self.cooled(message.author.id, "commentator", 60):
            asyncio.create_task(self.run_action("commentator", message.author))
            return
        options = [p for p in PASSIVE if p in t["trolls"] and (p != "read_aloud" or in_voice)]
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
            elif kind == "read_aloud" and message.content and self.cooled(message.author.id, "read", 20):
                text = re.sub(r"<[@#:][^>]+>|https?://\S+", "", message.content)[:250]
                if text.strip():
                    asyncio.create_task(self.say_in_call(message.author, f"{message.author.display_name} says: {text}",
                                                         own_voice=True))
            elif kind == "parrot":
                self.parrots[message.author.id] = time.time() + 180
                await message.channel.send(message.content[:2000] or "🦜", allowed_mentions=discord.AllowedMentions.none())
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
            await self.expire_shame()  # in case the bot restarted while someone was wearing it
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
                weights = [0.3 if o in RARE else 1.0 for o in options]
                action = random.choices(options, weights=weights)[0]
                asyncio.create_task(self.run_action(action, member))

    # ------------------------------------------------------------------ hidden owner commands
    async def hidden_command(self, message):
        """,,nick @user  ,,ghost @user  ,,fakeban @user  ,,shuffle @user  ,,mute @user  ,,report @user
        ,,mock @user  ,,unnick @user  ,,ambush @user  ,,blast @user  ,,tout @user  ,,vkick @user
        ,,shame @user  ,,unshame @user  ,,spree @user  ,,parrot @user
        ,,deafen @user  ,,stutter @user  ,,jail @user  ,,callout @user  ,,potato @user
        ,,tts @user <text>   (robot voice says anything in their call)
        ,,dead @user  ,,announce @user  ,,readstats @user
        ,,clone @user <text>   (opted-in voice clone of @user speaks in YOUR call, or theirs if you're not in one)
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
        elif cmd == "tts" and member and len(parts) > 2:
            text = " ".join(p for p in parts[1:] if not p.startswith("<@"))
            if member.voice and member.voice.channel:
                self.bot.stealth[member.id] = time.time() + 30
                asyncio.create_task(self.bot.get_cog("Soundboard").speak(member.voice.channel, text))
        elif cmd == "clone" and member and len(parts) > 2:
            text = " ".join(p for p in parts[1:] if not p.startswith("<@"))
            where = message.author.voice or member.voice
            if where and where.channel:
                asyncio.create_task(self.bot.get_cog("Soundboard").clone_speak(where.channel, member.id, text))
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
