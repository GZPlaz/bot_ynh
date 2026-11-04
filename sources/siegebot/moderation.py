import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

INVITE_RE = re.compile(r"(discord\.gg|discord(app)?\.com/invite)/\S+", re.I)
LINK_RE = re.compile(r"https?://([^/\s]+)", re.I)
EMOJI_RE = re.compile(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF☀-➿]")
DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.I)
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text):
    """'1h30m' -> seconds. Returns 0 if nothing parsed."""
    return sum(int(n) * UNITS[u.lower()] for n, u in DURATION_RE.findall(text or ""))


def human(seconds):
    for u, n in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= n and seconds % n == 0:
            return f"{seconds // n}{u}"
    return f"{seconds}s"


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.heat = {}  # (guild, user) -> (heat, last_ts)
        self.last_msgs = defaultdict(lambda: deque(maxlen=4))
        self.strikes = defaultdict(int)
        self.tempban_task = None

    async def cog_load(self):
        self.tempban_task = asyncio.create_task(self.tempban_loop())

    async def cog_unload(self):
        if self.tempban_task:
            self.tempban_task.cancel()

    def exempt(self, member):
        if member.guild_permissions.manage_messages or self.bot.is_trusted(member):
            return True
        roles = {str(r) for r in self.db.get("exempt_role_ids") or []}
        return any(str(r.id) in roles for r in member.roles)

    # ------------------------------------------------------------------ automod
    def add_heat(self, message):
        g = self.db.get
        now = time.time()
        key = (message.guild.id, message.author.id)
        heat, last = self.heat.get(key, (0.0, now))
        heat = max(0.0, heat - (now - last) * float(g("heat_decay")))
        content = message.content
        heat += float(g("heat_message"))
        heat += len(message.mentions) * float(g("heat_mention")) + len(message.role_mentions) * float(g("heat_mention"))
        heat += len(LINK_RE.findall(content)) * float(g("heat_link"))
        heat += len(message.attachments) * float(g("heat_attachment"))
        heat += len(EMOJI_RE.findall(content)) * float(g("heat_emoji"))
        heat += content.count("\n") * float(g("heat_newline"))
        norm = content.strip().lower()
        if norm and list(self.last_msgs[key]).count(norm) >= 1:
            heat += float(g("heat_duplicate"))
        self.last_msgs[key].append(norm)
        self.heat[key] = (heat, now)
        return heat

    async def check_message(self, message):
        """Returns True if the message was removed."""
        if not self.db.get("mod_enabled") or not isinstance(message.author, discord.Member):
            return False
        if self.exempt(message.author):
            return False
        g = self.db.get
        reason, heat_hit = None, False
        lower = message.content.lower()
        for w in g("banned_words") or []:
            w = w.strip().lower()
            if w and re.search(r"\b" + re.escape(w) + r"\b", lower):
                reason = "Used a banned word"
                break
        if not reason and g("filter_invites") and INVITE_RE.search(message.content):
            reason = "Posted an invite link"
        if not reason and int(g("mass_mention_limit") or 0) and \
                len(set(message.mentions)) + len(message.role_mentions) >= int(g("mass_mention_limit")):
            reason = "Mass mentions"
        if not reason and g("link_filter"):
            allowed = [d.lower().strip() for d in g("link_allowlist") or []]
            for host in LINK_RE.findall(message.content):
                host = host.lower().split(":")[0]
                if not any(host == d or host.endswith("." + d) for d in allowed):
                    reason = "Posted a non-allowed link"
                    break
        if not reason and g("filter_caps"):
            letters = [c for c in message.content if c.isalpha()]
            if len(letters) >= int(g("caps_min_length")) and sum(c.isupper() for c in letters) / len(letters) > 0.8:
                reason = "EXCESSIVE CAPS"
        if not reason and g("heat_enabled") and self.add_heat(message) >= float(g("heat_threshold")):
            reason, heat_hit = "Spam (heat limit reached)", True
            self.heat.pop((message.guild.id, message.author.id), None)
        if not reason:
            return False
        self.bot.suppress_delete_log.add(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        if heat_hit:
            await self.spam_cleanup(message)
            await self.punish(message.author, g("heat_action"), reason, notify_channel=message.channel)
        else:
            await self.add_warning(message.guild, message.author, self.bot.user, f"[auto] {reason}",
                                   notify_channel=message.channel)
        return True

    async def spam_cleanup(self, message):
        cutoff = discord.utils.utcnow() - timedelta(seconds=20)
        try:
            msgs = [m async for m in message.channel.history(limit=50, after=cutoff) if m.author == message.author]
            for m in msgs:
                self.bot.suppress_delete_log.add(m.id)
            if msgs:
                await message.channel.delete_messages(msgs)
        except discord.HTTPException:
            pass

    async def punish(self, member, action, reason, notify_channel=None, moderator=None):
        """Generic punishment used by automod, anti-raid and anti-nuke."""
        moderator = moderator or self.bot.user
        guild = member.guild
        try:
            if action == "warn":
                await self.add_warning(guild, member, moderator, reason, notify_channel)
                return
            if action == "timeout":
                self.strikes[(guild.id, member.id)] += 1
                mins = int(self.db.get("timeout_minutes")) * self.strikes[(guild.id, member.id)]
                await member.timeout(timedelta(minutes=min(mins, 40320)), reason=reason)
                self.db.add_case(guild.id, member, moderator, "timeout", reason, mins * 60)
                text = f"{member.mention} timed out for {mins} min. Reason: {reason}. Touch grass."
            elif action == "kick":
                await member.kick(reason=reason)
                self.db.add_case(guild.id, member, moderator, "kick", reason)
                text = f"{member} was kicked: {reason}"
            elif action == "ban":
                await member.ban(reason=reason, delete_message_days=1)
                self.db.add_case(guild.id, member, moderator, "ban", reason)
                text = f"{member} was banned: {reason}"
            elif action == "quarantine":
                await self.bot.get_cog("Security").quarantine(member, reason, moderator)
                text = f"{member.mention} was quarantined: {reason}"
            else:
                return
        except discord.HTTPException as e:
            await self.bot.send_log(guild, f"❌ Couldn't {action} {member}: {e.text or e.status}")
            return
        await self.bot.send_log(guild, f"🛡️ {action.upper()} {member} ({member.id}): {reason}")
        if notify_channel:
            await notify_channel.send(text, delete_after=20, allowed_mentions=discord.AllowedMentions(users=True))

    async def add_warning(self, guild, member, moderator, reason, notify_channel=None):
        cid = self.db.add_case(guild.id, member, moderator, "warn", reason)
        count = self.db.q("SELECT COUNT(*) c FROM cases WHERE guild_id=? AND user_id=? AND action='warn'",
                          (guild.id, member.id), one=True)["c"]
        maxw = int(self.db.get("max_warnings"))
        await self.bot.send_log(guild, f"⚠️ Case #{cid}: {member} warned by {moderator}: {reason} ({count}/{maxw})")
        if notify_channel:
            await notify_channel.send(f"{member.mention} ⚠️ {reason}. Warning {count}/{maxw}. "
                                      f"I'm not angry, just keeping receipts.", delete_after=15)
        if maxw and count >= maxw and count % maxw == 0:
            mins = int(self.db.get("timeout_minutes"))
            try:
                await member.timeout(timedelta(minutes=mins), reason=f"Reached {count} warnings")
                self.db.add_case(guild.id, member, self.bot.user, "timeout", f"Reached {count} warnings", mins * 60)
                await self.bot.send_log(guild, f"⏱️ {member} timed out for {mins} min (too many warnings)")
                if notify_channel:
                    await notify_channel.send(f"{member.mention} has been sent to the shadow realm for {mins} minutes. 👋",
                                              delete_after=30)
            except discord.HTTPException:
                pass
        return count

    async def tempban_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for row in self.db.q("SELECT * FROM tempbans WHERE until <= ?", (time.time(),)):
                guild = self.bot.get_guild(row["guild_id"])
                if guild:
                    try:
                        await guild.unban(discord.Object(row["user_id"]), reason="Temp-ban expired")
                        await self.bot.send_log(guild, f"🔓 Temp-ban expired for {row['user_id']}")
                    except discord.HTTPException:
                        pass
                self.db.q("DELETE FROM tempbans WHERE guild_id=? AND user_id=?", (row["guild_id"], row["user_id"]))
            await asyncio.sleep(60)

    async def _done(self, inter, case_action, member, reason, text, duration=None):
        cid = self.db.add_case(inter.guild.id, member, inter.user, case_action, reason, duration)
        await self.bot.send_log(inter.guild, f"🛡️ Case #{cid}: {case_action.upper()} {member} by {inter.user}: {reason}")
        if inter.response.is_done():
            await inter.followup.send(f"{text} (case #{cid})")
        else:
            await inter.response.send_message(f"{text} (case #{cid})")

    # ------------------------------------------------------------------ commands
    @app_commands.command(description="Warn a member")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, inter: discord.Interaction, member: discord.Member, reason: str):
        n = await self.add_warning(inter.guild, member, inter.user, reason)
        await inter.response.send_message(f"{member.mention} has been warned ({n} total): {reason}")

    @app_commands.command(description="Show a member's moderation history")
    @app_commands.default_permissions(moderate_members=True)
    async def modlogs(self, inter: discord.Interaction, member: discord.User):
        rows = self.db.q("SELECT * FROM cases WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 20",
                         (inter.guild.id, member.id))
        text = "\n".join(f"`#{r['id']}` **{r['action']}** <t:{int(r['ts'])}:R> by {r['mod_name']}: {r['reason']}"
                         for r in rows) or "Clean record. Suspicious."
        await inter.response.send_message(f"**Mod history for {member}:**\n{text}"[:2000], ephemeral=True)

    @app_commands.command(description="Look up a case by number")
    @app_commands.default_permissions(moderate_members=True)
    async def case(self, inter: discord.Interaction, number: int):
        r = self.db.q("SELECT * FROM cases WHERE id=? AND guild_id=?", (number, inter.guild.id), one=True)
        if not r:
            await inter.response.send_message("No such case.", ephemeral=True)
            return
        e = discord.Embed(title=f"Case #{r['id']}: {r['action']}", description=r["reason"], color=0xE5484D)
        e.add_field(name="User", value=f"{r['user_name']} ({r['user_id']})")
        e.add_field(name="Moderator", value=r["mod_name"])
        if r["duration"]:
            e.add_field(name="Duration", value=human(r["duration"]))
        e.add_field(name="When", value=f"<t:{int(r['ts'])}:f>")
        await inter.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(description="Add a private moderator note to a member")
    @app_commands.default_permissions(moderate_members=True)
    async def note(self, inter: discord.Interaction, member: discord.User, text: str):
        cid = self.db.add_case(inter.guild.id, member, inter.user, "note", text)
        await inter.response.send_message(f"📝 Note saved (case #{cid}).", ephemeral=True)

    @app_commands.command(description="Clear a member's warnings")
    @app_commands.default_permissions(moderate_members=True)
    async def clearwarns(self, inter: discord.Interaction, member: discord.Member):
        self.db.q("DELETE FROM cases WHERE guild_id=? AND user_id=? AND action='warn'", (inter.guild.id, member.id))
        await self.bot.send_log(inter.guild, f"🧹 {inter.user} cleared warnings for {member}")
        await inter.response.send_message(f"Warnings cleared for {member.mention}. Fresh start. Don't waste it.")

    @app_commands.command(description="Timeout (mute) a member, e.g. duration 10m, 2h, 1d")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, inter: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason given"):
        secs = parse_duration(duration)
        if not 0 < secs <= 28 * 86400:
            await inter.response.send_message("Duration must be between 1s and 28d (e.g. `10m`, `2h`).", ephemeral=True)
            return
        await member.timeout(timedelta(seconds=secs), reason=reason)
        await self._done(inter, "timeout", member, reason, f"{member.mention} is in timeout for {human(secs)}. Think about your rotates.", secs)

    @app_commands.command(description="Remove a timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def untimeout(self, inter: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await self._done(inter, "untimeout", member, "-", f"{member.mention} is free. Behave.")

    @app_commands.command(description="Delete recent messages (optionally only from one member)")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, inter: discord.Interaction, amount: app_commands.Range[int, 1, 500], member: discord.Member = None,
                    bots_only: bool = False):
        await inter.response.defer(ephemeral=True)

        def check(m):
            return (member is None or m.author == member) and (not bots_only or m.author.bot)
        deleted = await inter.channel.purge(limit=amount, check=check)
        for m in deleted:
            self.bot.suppress_delete_log.add(m.id)
        await self.bot.send_log(inter.guild, f"🧹 {inter.user} purged {len(deleted)} messages in #{inter.channel}")
        await inter.followup.send(f"Yeeted {len(deleted)} messages into the void.", ephemeral=True)

    @app_commands.command(description="Kick a member")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
        await member.kick(reason=reason)
        await self._done(inter, "kick", member, reason, f"{member} has been kicked. Like a Sledge hammer to a soft wall.")

    @app_commands.command(description="Ban a member; optional duration (e.g. 7d) makes it a temp-ban")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, inter: discord.Interaction, member: discord.User, reason: str = "No reason given",
                  duration: str = "", delete_days: app_commands.Range[int, 0, 7] = 0):
        secs = parse_duration(duration)
        await inter.guild.ban(member, reason=reason, delete_message_days=delete_days)
        if secs:
            self.db.q("INSERT OR REPLACE INTO tempbans(guild_id,user_id,until) VALUES(?,?,?)",
                      (inter.guild.id, member.id, time.time() + secs))
        await self._done(inter, "tempban" if secs else "ban", member, reason,
                         f"🔨 {member} has been banned{' for ' + human(secs) if secs else ''}. This one's real. No jk.", secs or None)

    @app_commands.command(description="Unban a user by ID")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, inter: discord.Interaction, user_id: str, reason: str = "No reason given"):
        user = await self.bot.fetch_user(int(user_id))
        await inter.guild.unban(user, reason=reason)
        self.db.q("DELETE FROM tempbans WHERE guild_id=? AND user_id=?", (inter.guild.id, user.id))
        await self._done(inter, "unban", user, reason, f"{user} has been unbanned. Redemption arc incoming.")

    @app_commands.command(description="Ban + immediate unban to wipe a member's recent messages")
    @app_commands.default_permissions(ban_members=True)
    async def softban(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
        await member.ban(reason=f"Softban: {reason}", delete_message_days=1)
        await inter.guild.unban(member, reason="Softban")
        await self._done(inter, "softban", member, reason, f"{member} softbanned. Messages wiped, door left open.")

    @app_commands.command(description="Set slowmode for this channel (seconds, 0 = off)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(self, inter: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await inter.channel.edit(slowmode_delay=seconds)
        await inter.response.send_message(f"🐌 Slowmode set to {seconds}s." if seconds else "Slowmode off. Chaos resumes.")

    @app_commands.command(description="Change a member's nickname")
    @app_commands.default_permissions(manage_nicknames=True)
    async def nick(self, inter: discord.Interaction, member: discord.Member, nickname: str = None):
        await member.edit(nick=nickname)
        await inter.response.send_message(f"Renamed {member.mention}.", ephemeral=True)

    @app_commands.command(description="Info about a member")
    @app_commands.default_permissions(moderate_members=True)
    async def userinfo(self, inter: discord.Interaction, member: discord.Member):
        n = self.db.q("SELECT action, COUNT(*) c FROM cases WHERE guild_id=? AND user_id=? GROUP BY action",
                      (inter.guild.id, member.id))
        e = discord.Embed(title=str(member), color=member.color)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="ID", value=str(member.id))
        e.add_field(name="Account created", value=f"<t:{int(member.created_at.timestamp())}:R>")
        e.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "?")
        e.add_field(name="Roles", value=", ".join(r.mention for r in member.roles[1:][-10:]) or "none", inline=False)
        e.add_field(name="Cases", value=", ".join(f"{r['action']}: {r['c']}" for r in n) or "none", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    async def cog_app_command_error(self, inter, error):
        msg = "I tried. Discord said no (check my role is above theirs and I have the permission)."
        if isinstance(getattr(error, "original", None), (ValueError, discord.NotFound)):
            msg = "Couldn't find that user/ID."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)
