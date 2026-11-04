import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

INVITE_RE = re.compile(r"(discord\.gg|discord(app)?\.com/invite)/\S+", re.I)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.recent = defaultdict(lambda: deque(maxlen=50))

    def exempt(self, member):
        if member.guild_permissions.manage_messages or self.bot.is_boss(member):
            return True
        roles = {str(r) for r in self.db.get("exempt_role_ids") or []}
        return any(str(r.id) in roles for r in member.roles)

    async def check_message(self, message):
        """Returns True if the message was removed."""
        if not self.db.get("mod_enabled") or not isinstance(message.author, discord.Member):
            return False
        if self.exempt(message.author):
            return False
        reason = None
        lower = message.content.lower()
        for w in self.db.get("banned_words") or []:
            w = w.strip().lower()
            if w and re.search(r"\b" + re.escape(w) + r"\b", lower):
                reason = "Used a banned word"
                break
        if not reason and self.db.get("filter_invites") and INVITE_RE.search(message.content):
            reason = "Posted an invite link"
        if not reason and self.db.get("filter_caps"):
            letters = [c for c in message.content if c.isalpha()]
            if len(letters) >= int(self.db.get("caps_min_length")) and sum(c.isupper() for c in letters) / len(letters) > 0.8:
                reason = "EXCESSIVE CAPS"
        if not reason and self.db.get("anti_spam"):
            now = time.time()
            q = self.recent[message.author.id]
            q.append(now)
            window = float(self.db.get("spam_seconds"))
            if sum(1 for t in q if now - t < window) >= int(self.db.get("spam_messages")):
                reason = "Spamming"
                q.clear()
        if not reason:
            return False
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        await self.add_warning(message.guild, message.author, self.bot.user, f"[auto] {reason}",
                               notify_channel=message.channel)
        return True

    async def add_warning(self, guild, member, moderator, reason, notify_channel=None):
        self.db.q("INSERT INTO warnings(guild_id,user_id,user_name,mod_name,reason,ts) VALUES(?,?,?,?,?,?)",
                  (guild.id, member.id, str(member), str(moderator), reason, time.time()))
        count = self.db.q("SELECT COUNT(*) c FROM warnings WHERE guild_id=? AND user_id=?",
                          (guild.id, member.id), one=True)["c"]
        maxw = int(self.db.get("max_warnings"))
        await self.bot.send_log(guild, f"⚠️ {member} warned by {moderator}: {reason} ({count}/{maxw})")
        if notify_channel:
            await notify_channel.send(f"{member.mention} ⚠️ {reason}. Warning {count}/{maxw}. "
                                      f"I'm not angry, just keeping receipts.", delete_after=15)
        if maxw and count >= maxw and count % maxw == 0:
            mins = int(self.db.get("timeout_minutes"))
            try:
                await member.timeout(timedelta(minutes=mins), reason=f"Reached {count} warnings")
                await self.bot.send_log(guild, f"⏱️ {member} timed out for {mins} min (too many warnings)")
                if notify_channel:
                    await notify_channel.send(f"{member.mention} has been sent to the shadow realm for {mins} minutes. 👋",
                                              delete_after=30)
            except discord.HTTPException:
                pass
        return count

    # ---- slash commands ----
    @app_commands.command(description="Warn a member")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, inter: discord.Interaction, member: discord.Member, reason: str):
        n = await self.add_warning(inter.guild, member, inter.user, reason)
        await inter.response.send_message(f"{member.mention} has been warned ({n} total): {reason}")

    @app_commands.command(description="List a member's warnings")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, inter: discord.Interaction, member: discord.Member):
        rows = self.db.q("SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 15",
                         (inter.guild.id, member.id))
        text = "\n".join(f"• <t:{int(r['ts'])}:R> by {r['mod_name']}: {r['reason']}" for r in rows) or "Clean record. Suspicious."
        await inter.response.send_message(f"**Warnings for {member}:**\n{text}", ephemeral=True)

    @app_commands.command(description="Clear a member's warnings")
    @app_commands.default_permissions(moderate_members=True)
    async def clearwarns(self, inter: discord.Interaction, member: discord.Member):
        self.db.q("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (inter.guild.id, member.id))
        await self.bot.send_log(inter.guild, f"🧹 {inter.user} cleared warnings for {member}")
        await inter.response.send_message(f"Warnings cleared for {member.mention}. Fresh start. Don't waste it.")

    @app_commands.command(description="Timeout a member")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, inter: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320],
                      reason: str = "No reason given"):
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await self.bot.send_log(inter.guild, f"⏱️ {inter.user} timed out {member} for {minutes} min: {reason}")
        await inter.response.send_message(f"{member.mention} is in timeout for {minutes} min. Think about your rotates.")

    @app_commands.command(description="Delete recent messages")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, inter: discord.Interaction, amount: app_commands.Range[int, 1, 200]):
        await inter.response.defer(ephemeral=True)
        deleted = await inter.channel.purge(limit=amount)
        await self.bot.send_log(inter.guild, f"🧹 {inter.user} purged {len(deleted)} messages in #{inter.channel}")
        await inter.followup.send(f"Yeeted {len(deleted)} messages into the void.", ephemeral=True)

    @app_commands.command(description="Kick a member")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
        await member.kick(reason=reason)
        await self.bot.send_log(inter.guild, f"👢 {inter.user} kicked {member}: {reason}")
        await inter.response.send_message(f"{member} has been kicked. Like a Sledge hammer to a soft wall.")

    @app_commands.command(description="Ban a member (for real)")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
        await member.ban(reason=reason, delete_message_days=0)
        await self.bot.send_log(inter.guild, f"🔨 {inter.user} banned {member}: {reason}")
        await inter.response.send_message(f"🔨 {member} has been banned. This one's real. No jk.")

    async def cog_app_command_error(self, inter, error):
        msg = "I tried. Discord said no (check my role is above theirs and I have the permission)."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)
