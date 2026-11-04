"""Server protection: anti-nuke, anti-raid, verification gate, quarantine, lockdown, whitelist."""
import asyncio
import json
import random
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

A = discord.AuditLogAction
NUKE_KINDS = {A.channel_delete: "channel_delete", A.channel_create: "channel_create", A.role_delete: "role_delete",
              A.role_create: "role_create", A.ban: "ban", A.kick: "kick", A.webhook_create: "webhook"}
DANGEROUS = ["administrator", "ban_members", "kick_members", "manage_guild", "manage_roles", "manage_channels",
             "manage_webhooks", "mention_everyone"]


def dangerous(perms):
    return {p for p in DANGEROUS if getattr(perms, p, False)}


class VerifyButton(discord.ui.View):
    """Persistent button posted by /verifypanel."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Verify", emoji="✅", style=discord.ButtonStyle.success, custom_id="siegebot:verify")
    async def verify(self, inter: discord.Interaction, _button):
        role = self.cog.verified_role(inter.guild)
        if not role:
            await inter.response.send_message("Verification isn't set up. Yell at an admin.", ephemeral=True)
            return
        if role in inter.user.roles:
            await inter.response.send_message("You're already verified. Overachiever.", ephemeral=True)
            return
        a, b = random.randint(2, 12), random.randint(2, 12)
        answers = {a + b}
        while len(answers) < 4:
            answers.add(a + b + random.randint(-6, 6))
        await inter.response.send_message(f"🤖 Prove you're not a bot (unlike me): **what is {a} + {b}?**",
                                          view=Captcha(self.cog, role, a + b, sorted(answers)), ephemeral=True)


class Captcha(discord.ui.View):
    def __init__(self, cog, role, answer, options):
        super().__init__(timeout=120)
        for opt in options:
            btn = discord.ui.Button(label=str(opt), style=discord.ButtonStyle.secondary)
            btn.callback = self.make_cb(cog, role, opt == answer)
            self.add_item(btn)

    @staticmethod
    def make_cb(cog, role, correct):
        async def cb(inter: discord.Interaction):
            if not correct:
                await inter.response.edit_message(content="❌ Wrong. Math is hard, I know. Click Verify to try again.", view=None)
                return
            try:
                await inter.user.add_roles(role, reason="Passed verification")
            except discord.HTTPException:
                await inter.response.edit_message(content="I couldn't give you the role (my role is too low).", view=None)
                return
            await inter.response.edit_message(content="✅ Verified. Welcome. Don't spawn peek.", view=None)
            await cog.bot.send_log(inter.guild, f"✅ {inter.user} passed verification")
        return cb


class Security(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.actions = defaultdict(deque)  # (guild, user) -> deque[(ts, kind, target_id)]
        self.punished = {}  # (guild, user) -> ts
        self.deleted_cache = {}  # id -> (ts, channel/role object)
        self.joins = defaultdict(deque)
        self.raid_until = {}

    async def cog_load(self):
        self.bot.add_view(VerifyButton(self))

    def g(self, key):
        return self.db.get(key)

    async def alert(self, guild, text):
        await self.bot.send_log(guild, text)
        for uid in set(self.bot.owner_id_set) | {guild.owner_id}:
            user = self.bot.get_user(uid)
            if user:
                try:
                    await user.send(f"**[{guild.name}]** {text}")
                except discord.HTTPException:
                    pass

    # ------------------------------------------------------------------ anti-nuke
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        self.deleted_cache[channel.id] = (time.time(), channel)
        self._trim_cache()

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        self.deleted_cache[role.id] = (time.time(), role)
        self._trim_cache()

    def _trim_cache(self):
        cutoff = time.time() - 600
        for k in [k for k, (ts, _) in self.deleted_cache.items() if ts < cutoff]:
            del self.deleted_cache[k]

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        if not self.g("antinuke_enabled") or entry.user_id in (None, self.bot.user.id):
            return
        executor = guild.get_member(entry.user_id)
        if executor is None or self.bot.is_trusted(executor):
            return

        if entry.action == A.bot_add and self.g("antibot_add"):
            added = guild.get_member(getattr(entry.target, "id", 0))
            if added:
                try:
                    await added.kick(reason=f"Unauthorized bot added by {executor}")
                except discord.HTTPException:
                    pass
            await self.alert(guild, f"🤖 {executor} added bot `{getattr(entry.target, 'id', '?')}` without being whitelisted. Kicked it.")
            return

        if entry.action == A.role_update and self.g("protect_dangerous_perms"):
            before = getattr(entry.changes.before, "permissions", None)
            after = getattr(entry.changes.after, "permissions", None)
            if before is not None and after is not None and dangerous(after) - dangerous(before):
                role = guild.get_role(entry.target.id)
                if role:
                    try:
                        await role.edit(permissions=before, reason="Anti-nuke: dangerous permission grant reverted")
                    except discord.HTTPException:
                        pass
                await self.nuke_punish(guild, executor, f"granted dangerous permissions {sorted(dangerous(after) - dangerous(before))} to a role")
            return

        if entry.action == A.member_role_update and self.g("protect_dangerous_perms"):
            added = getattr(entry.changes.after, "roles", None) or []
            bad = [r for r in added if isinstance(r, discord.Role) and dangerous(r.permissions)]
            target = guild.get_member(getattr(entry.target, "id", 0))
            if bad and target:
                try:
                    await target.remove_roles(*bad, reason="Anti-nuke: dangerous role given by untrusted user")
                except discord.HTTPException:
                    pass
                await self.nuke_punish(guild, executor, f"gave dangerous role(s) {', '.join(r.name for r in bad)} to {target}")
            return

        kind = NUKE_KINDS.get(entry.action)
        if not kind:
            return
        key = (guild.id, executor.id)
        now = time.time()
        window = float(self.g("antinuke_window"))
        q = self.actions[key]
        q.append((now, kind, getattr(entry.target, "id", None)))
        while q and now - q[0][0] > window:
            q.popleft()
        count = sum(1 for _, k, _ in q if k == kind)
        if count >= int(self.g(f"nuke_{kind}") or 999) and now - self.punished.get(key, 0) > window:
            self.punished[key] = now
            await self.nuke_punish(guild, executor, f"{count}× {kind.replace('_', ' ')} in {int(window)}s")
            if self.g("antinuke_restore"):
                await self.restore(guild, list(q))

    async def nuke_punish(self, guild, member, reason):
        action = self.g("antinuke_punishment")
        try:
            if action == "ban":
                await member.ban(reason=f"Anti-nuke: {reason}")
            elif action == "kick":
                await member.kick(reason=f"Anti-nuke: {reason}")
            elif action == "strip":
                await member.remove_roles(*[r for r in member.roles if not r.is_default() and not r.managed],
                                          reason=f"Anti-nuke: {reason}")
            else:
                await self.quarantine(member, f"Anti-nuke: {reason}", self.bot.user)
            self.db.add_case(guild.id, member, self.bot.user, f"antinuke-{action}", reason)
            result = f"Punishment: **{action}**."
        except discord.HTTPException as e:
            result = f"⚠️ Couldn't punish them ({e.status}); move my role higher!"
        await self.alert(guild, f"🚨 **ANTI-NUKE** triggered by {member} ({member.id}): {reason}. {result}")

    async def restore(self, guild, events):
        restored = 0
        for _, kind, target_id in events:
            try:
                if kind == "channel_delete" and target_id in self.deleted_cache:
                    await self.deleted_cache.pop(target_id)[1].clone(reason="Anti-nuke restore")
                elif kind == "role_delete" and target_id in self.deleted_cache:
                    r = self.deleted_cache.pop(target_id)[1]
                    await guild.create_role(name=r.name, permissions=r.permissions, colour=r.colour, hoist=r.hoist,
                                            mentionable=r.mentionable, reason="Anti-nuke restore")
                elif kind == "channel_create" and (ch := guild.get_channel(target_id)):
                    await ch.delete(reason="Anti-nuke cleanup")
                elif kind == "role_create" and (role := guild.get_role(target_id)):
                    await role.delete(reason="Anti-nuke cleanup")
                elif kind == "ban" and target_id:
                    await guild.unban(discord.Object(target_id), reason="Anti-nuke: reverting mass ban")
                else:
                    continue
                restored += 1
            except discord.HTTPException:
                pass
        if restored:
            await self.bot.send_log(guild, f"♻️ Anti-nuke reverted {restored} action(s). Deleted roles come back empty, so reassign members.")

    # ------------------------------------------------------------------ anti-raid
    def raid_active(self, guild):
        return self.raid_until.get(guild.id, 0) > time.time()

    async def set_raid(self, guild, on, by="auto-detection"):
        if on:
            self.raid_until[guild.id] = time.time() + 60 * float(self.g("raid_duration_minutes"))
            await self.alert(guild, f"🚨 **RAID MODE ON** ({by}). New joins get: {self.g('raid_action')}.")
            if self.g("raid_auto_lockdown"):
                await self.lockdown(guild, True)
        else:
            self.raid_until.pop(guild.id, None)
            await self.bot.send_log(guild, f"✅ Raid mode off ({by}).")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot or not self.g("antiraid_enabled"):
            return
        guild, now = member.guild, time.time()
        q = self.joins[guild.id]
        q.append(now)
        while q and now - q[0] > float(self.g("raid_seconds")):
            q.popleft()
        if len(q) >= int(self.g("raid_joins")) and not self.raid_active(guild):
            await self.set_raid(guild, True, f"{len(q)} joins in {self.g('raid_seconds')}s")
        action, reason = None, None
        if self.raid_active(guild):
            action, reason = self.g("raid_action"), "Joined during a raid"
        elif int(self.g("min_account_age_days") or 0):
            age_days = (discord.utils.utcnow() - member.created_at).days
            if age_days < int(self.g("min_account_age_days")):
                action, reason = self.g("young_account_action"), f"Account too new ({age_days}d old)"
        if not action and member.avatar is None and self.g("no_avatar_action") != "none":
            action, reason = self.g("no_avatar_action"), "No avatar (likely alt/bot)"
        if action and action != "none":
            if action in ("kick", "ban"):
                try:
                    await member.send(f"You were removed from **{guild.name}** by automatic protection: {reason}. "
                                      "If this was a mistake, try again later.")
                except discord.HTTPException:
                    pass
            await self.bot.get_cog("Moderation").punish(member, action, reason)

    # ------------------------------------------------------------------ verification
    def verified_role(self, guild):
        rid = str(self.g("verified_role_id"))
        return guild.get_role(int(rid)) if self.g("verify_enabled") and rid.isdigit() else None

    # ------------------------------------------------------------------ quarantine
    async def quarantine_role(self, guild):
        rid = str(self.g("quarantine_role_id"))
        role = guild.get_role(int(rid)) if rid.isdigit() else None
        if role:
            return role
        role = await guild.create_role(name="Quarantined", permissions=discord.Permissions.none(),
                                       colour=discord.Colour.dark_grey(), reason="SiegeBot quarantine role")
        self.db.set("quarantine_role_id", str(role.id))
        for ch in guild.channels:
            try:
                await ch.set_permissions(role, view_channel=False, send_messages=False, connect=False,
                                         reason="Quarantine role setup")
            except discord.HTTPException:
                pass
        return role

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        rid = str(self.g("quarantine_role_id"))
        role = channel.guild.get_role(int(rid)) if rid.isdigit() else None
        if role:
            try:
                await channel.set_permissions(role, view_channel=False, send_messages=False, connect=False)
            except discord.HTTPException:
                pass

    async def quarantine(self, member, reason, moderator):
        role = await self.quarantine_role(member.guild)
        keep = [r for r in member.roles if r.is_default() or r.managed or r == role]
        removed = [r for r in member.roles if r not in keep]
        self.db.q("INSERT OR REPLACE INTO quarantined(guild_id,user_id,roles,ts) VALUES(?,?,?,?)",
                  (member.guild.id, member.id, json.dumps([r.id for r in removed]), time.time()))
        await member.edit(roles=keep + [role], reason=f"Quarantine: {reason}")
        if member.voice:
            await member.move_to(None)
        self.db.add_case(member.guild.id, member, moderator, "quarantine", reason)

    async def unquarantine(self, member, moderator):
        row = self.db.q("SELECT * FROM quarantined WHERE guild_id=? AND user_id=?", (member.guild.id, member.id), one=True)
        role = await self.quarantine_role(member.guild)
        roles = [member.guild.get_role(r) for r in json.loads(row["roles"])] if row else []
        roles = [r for r in roles if r and r < member.guild.me.top_role]
        new = [r for r in member.roles if r != role] + [r for r in roles if r not in member.roles]
        await member.edit(roles=new, reason=f"Unquarantined by {moderator}")
        self.db.q("DELETE FROM quarantined WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
        self.db.add_case(member.guild.id, member, moderator, "unquarantine", "-")

    # ------------------------------------------------------------------ lockdown
    async def lock_channel(self, channel, on):
        state = self.g("lockdown_state") or {}
        gs = state.setdefault(str(channel.guild.id), {})
        ow = channel.overwrites_for(channel.guild.default_role)
        if on:
            if str(channel.id) not in gs:
                gs[str(channel.id)] = ow.send_messages
            ow.send_messages = False
        else:
            ow.send_messages = gs.pop(str(channel.id), None)
        await channel.set_permissions(channel.guild.default_role, overwrite=ow,
                                      reason="Lockdown" if on else "Lockdown lifted")
        self.db.set("lockdown_state", state)

    async def lockdown(self, guild, on):
        n = 0
        for ch in guild.text_channels:
            if not on and str(ch.id) not in (self.g("lockdown_state") or {}).get(str(guild.id), {}):
                continue
            try:
                await self.lock_channel(ch, on)
                n += 1
            except discord.HTTPException:
                pass
        await self.bot.send_log(guild, f"{'🔒 Lockdown' if on else '🔓 Lockdown lifted'}: {n} channel(s)")
        return n

    # ------------------------------------------------------------------ commands
    @app_commands.command(description="Lock a channel (nobody can talk)")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, inter: discord.Interaction, channel: discord.TextChannel = None):
        await self.lock_channel(channel or inter.channel, True)
        await inter.response.send_message("🔒 Channel locked. Silence, peasants.")

    @app_commands.command(description="Unlock a channel")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, inter: discord.Interaction, channel: discord.TextChannel = None):
        await self.lock_channel(channel or inter.channel, False)
        await inter.response.send_message("🔓 Channel unlocked. Try to behave.")

    @app_commands.command(name="lockdown", description="Lock or unlock every text channel")
    @app_commands.default_permissions(administrator=True)
    async def lockdown_cmd(self, inter: discord.Interaction, state: Literal["on", "off"]):
        await inter.response.defer()
        n = await self.lockdown(inter.guild, state == "on")
        await inter.followup.send(f"{'🔒 Server locked down' if state == 'on' else '🔓 Lockdown lifted'} ({n} channels).")


    @app_commands.command(name="quarantine", description="Quarantine a member (strips roles, hides all channels)")
    @app_commands.default_permissions(moderate_members=True)
    async def quarantine_cmd(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
        await inter.response.defer()
        await self.quarantine(member, reason, inter.user)
        await self.bot.send_log(inter.guild, f"☣️ {inter.user} quarantined {member}: {reason}")
        await inter.followup.send(f"☣️ {member.mention} has been quarantined. Nobody touch them.")


    @app_commands.command(name="unquarantine", description="Release a member from quarantine and restore their roles")
    @app_commands.default_permissions(moderate_members=True)
    async def unquarantine_cmd(self, inter: discord.Interaction, member: discord.Member):
        await inter.response.defer()
        await self.unquarantine(member, inter.user)
        await inter.followup.send(f"{member.mention} is out of quarantine. Roles restored.")


    @app_commands.command(description="Manually toggle raid mode")
    @app_commands.default_permissions(administrator=True)
    async def raidmode(self, inter: discord.Interaction, state: Literal["on", "off"]):
        await self.set_raid(inter.guild, state == "on", f"manual, by {inter.user}")
        await inter.response.send_message(f"Raid mode **{state}**.")

    @app_commands.command(description="Post the verification button in this channel")
    @app_commands.default_permissions(administrator=True)
    async def verifypanel(self, inter: discord.Interaction):
        if not self.verified_role(inter.guild):
            await inter.response.send_message("Enable verification and pick the verified role in the admin panel first.",
                                              ephemeral=True)
            return
        e = discord.Embed(title="✅ Verification",
                          description="Click the button and solve a very hard math problem to get access.\n"
                                      "Bots, raiders and people who spawn-peek need not apply.", color=0x30A46C)
        await inter.channel.send(embed=e, view=VerifyButton(self))
        await inter.response.send_message("Posted.", ephemeral=True)

    whitelist = app_commands.Group(name="whitelist", description="Trusted users/roles that bypass anti-nuke and automod",
                                   default_permissions=discord.Permissions(administrator=True))

    async def _owner_check(self, inter):
        if inter.user.id == inter.guild.owner_id or self.bot.is_boss(inter.user):
            return True
        await inter.response.send_message("Only the server owner or bot owners can edit the whitelist.", ephemeral=True)
        return False

    @whitelist.command(name="add", description="Trust a user or role")
    async def wl_add(self, inter: discord.Interaction, target: discord.Member | discord.Role):
        if not await self._owner_check(inter):
            return
        wl = [str(x) for x in self.g("whitelist_ids") or []]
        if str(target.id) not in wl:
            wl.append(str(target.id))
        self.db.set("whitelist_ids", wl)
        await inter.response.send_message(f"Whitelisted {target.mention}.", ephemeral=True)

    @whitelist.command(name="remove", description="Untrust a user or role")
    async def wl_remove(self, inter: discord.Interaction, target: discord.Member | discord.Role):
        if not await self._owner_check(inter):
            return
        self.db.set("whitelist_ids", [x for x in self.g("whitelist_ids") or [] if str(x) != str(target.id)])
        await inter.response.send_message(f"Removed {target.mention} from the whitelist.", ephemeral=True)

    @whitelist.command(name="list", description="Show the whitelist")
    async def wl_list(self, inter: discord.Interaction):
        items = []
        for x in self.g("whitelist_ids") or []:
            obj = inter.guild.get_member(int(x)) or inter.guild.get_role(int(x)) if str(x).isdigit() else None
            items.append(obj.mention if obj else f"`{x}`")
        await inter.response.send_message("Whitelist: " + (", ".join(items) or "empty (owners are always trusted)"),
                                          ephemeral=True)

    async def cog_app_command_error(self, inter, error):
        msg = "Discord said no. Make sure my role is near the top and I have Administrator or the needed permissions."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)
