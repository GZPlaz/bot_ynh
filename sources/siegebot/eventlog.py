"""Server event logs + ghost-ping detector. Anything the troll engine does is kept out of the logs."""
import time

import discord
from discord.ext import commands


class EventLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def channel(self, guild, category):
        if not self.db.get(f"log_{category}"):
            return None
        cid = str(self.db.get("event_log_channel_id"))
        return guild.get_channel(int(cid)) if cid.isdigit() else None

    async def emit(self, guild, category, title, desc, color=0x5865F2, member=None):
        ch = self.channel(guild, category)
        if not ch:
            return
        e = discord.Embed(title=title, description=desc[:4000], color=color, timestamp=discord.utils.utcnow())
        if member:
            e.set_author(name=str(member), icon_url=member.display_avatar.url)
            e.set_footer(text=f"ID {member.id}")
        try:
            await ch.send(embed=e)
        except discord.HTTPException:
            pass

    def stealthy(self, user_id):
        return self.bot.stealth.get(user_id, 0) > time.time()

    # ---------------- messages
    @commands.Cog.listener()
    async def on_message_delete(self, m):
        if not m.guild or m.author.bot or m.id in self.bot.suppress_delete_log or m.content.startswith(",,"):
            self.bot.suppress_delete_log.discard(m.id)
            return
        pinged = [u for u in m.mentions if not u.bot and u != m.author] + list(m.role_mentions)
        age = (discord.utils.utcnow() - m.created_at).total_seconds()
        if pinged and age < 60 and self.db.get("ghost_ping_detector"):
            try:
                await m.channel.send(f"👻 **Ghost ping detected!** {m.author.mention} pinged "
                                     f"{', '.join(p.mention for p in pinged)} and deleted it. Coward.",
                                     allowed_mentions=discord.AllowedMentions(users=True, roles=False))
            except discord.HTTPException:
                pass
        await self.emit(m.guild, "messages", f"🗑️ Message deleted in #{m.channel}",
                        (m.content or "*no text*") + ("\n📎 " + ", ".join(a.filename for a in m.attachments) if m.attachments else ""),
                        0xE5484D, m.author)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, msgs):
        msgs = [m for m in msgs if m.id not in self.bot.suppress_delete_log]
        if msgs and msgs[0].guild:
            await self.emit(msgs[0].guild, "messages", f"🗑️ {len(msgs)} messages bulk-deleted in #{msgs[0].channel}", "", 0xE5484D)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        await self.emit(before.guild, "messages", f"✏️ Message edited in #{before.channel}",
                        f"**Before:** {before.content[:1800]}\n**After:** {after.content[:1800]}\n[Jump]({after.jump_url})",
                        0xF5A623, before.author)

    # ---------------- members
    @commands.Cog.listener()
    async def on_member_join(self, m):
        age = (discord.utils.utcnow() - m.created_at).days
        await self.emit(m.guild, "members", "📥 Member joined",
                        f"{m.mention}, account age **{age} days**{' ⚠️ NEW ACCOUNT' if age < 7 else ''}", 0x30A46C, m)

    @commands.Cog.listener()
    async def on_member_remove(self, m):
        roles = ", ".join(r.name for r in m.roles[1:]) or "none"
        await self.emit(m.guild, "members", "📤 Member left", f"{m.mention}\nRoles: {roles}", 0x8B93A3, m)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.emit(guild, "members", "🔨 Member banned", f"{user} ({user.id})", 0xE5484D)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.emit(guild, "members", "🔓 Member unbanned", f"{user} ({user.id})", 0x30A46C)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if self.stealthy(after.id):
            return
        if before.nick != after.nick:
            await self.emit(after.guild, "members", "🏷️ Nickname changed",
                            f"`{before.nick or before.name}` → `{after.nick or after.name}`", 0x5865F2, after)
        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            desc = (f"**Added:** {', '.join(added)}\n" if added else "") + (f"**Removed:** {', '.join(removed)}" if removed else "")
            await self.emit(after.guild, "roles", "🎭 Roles updated", desc, 0x5865F2, after)
        if before.timed_out_until != after.timed_out_until and after.timed_out_until:
            await self.emit(after.guild, "members", "⏱️ Timed out",
                            f"Until <t:{int(after.timed_out_until.timestamp())}:f>", 0xF5A623, after)

    # ---------------- voice
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or self.stealthy(member.id) or before.channel == after.channel or \
                any(c and c.id in self.bot.suppress_channel_log for c in (before.channel, after.channel)):
            return
        if not before.channel:
            text = f"🔊 joined **{after.channel}**"
        elif not after.channel:
            text = f"🔇 left **{before.channel}**"
        else:
            text = f"🔀 moved **{before.channel}** → **{after.channel}**"
        await self.emit(member.guild, "voice", "Voice", f"{member.mention} {text}", 0x8B5CF6, member)

    # ---------------- server
    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        if ch.id in self.bot.suppress_channel_log or ch.name in (self.db.get("jail_names") or []):
            return
        await self.emit(ch.guild, "server", "➕ Channel created", f"{ch.mention} ({ch.type})", 0x30A46C)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        if ch.id in self.bot.suppress_channel_log or ch.name in (self.db.get("jail_names") or []):
            return
        await self.emit(ch.guild, "server", "➖ Channel deleted", f"#{ch.name} ({ch.type})", 0xE5484D)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.emit(role.guild, "roles", "➕ Role created", role.mention, 0x30A46C)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.emit(role.guild, "roles", "➖ Role deleted", f"@{role.name}", 0xE5484D)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if before.permissions != after.permissions or before.name != after.name:
            gained = [p for p, v in after.permissions if v and not getattr(before.permissions, p)]
            lost = [p for p, v in after.permissions if not v and getattr(before.permissions, p)]
            await self.emit(after.guild, "roles", "🛠️ Role updated",
                            f"{after.mention}" + (f"\nName: `{before.name}` → `{after.name}`" if before.name != after.name else "")
                            + (f"\n**+** {', '.join(gained)}" if gained else "") + (f"\n**−** {', '.join(lost)}" if lost else ""),
                            0xF5A623)
