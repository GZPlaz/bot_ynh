"""Tier leaderboard (Tier 1 = best, Tier 5 = worst) with suggested revisions that need approval."""
import time

import discord
from discord import app_commands
from discord.ext import commands

TIER_EMOJI = {1: "🏆", 2: "🔥", 3: "👍", 4: "🎲", 5: "🤖"}


class ReviewButton(discord.ui.DynamicItem[discord.ui.Button], template=r"siegebot:tier:(?P<action>ok|no):(?P<rid>\d+)"):
    """Approve/reject buttons on a revision request. Survive restarts via the custom_id."""

    def __init__(self, action: str, rid: int):
        approve = action == "ok"
        super().__init__(discord.ui.Button(label="Approve" if approve else "Reject", emoji="✅" if approve else "❌",
                                           style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
                                           custom_id=f"siegebot:tier:{action}:{rid}"))
        self.action, self.rid = action, rid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["rid"]))

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Leaderboard")
        err = cog.review_denied(interaction.user, self.rid)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        if self.action == "no":
            await interaction.response.send_modal(RejectModal(cog, self.rid))
            return
        await interaction.response.defer()
        msg = await cog.review(self.rid, True, str(interaction.user))
        await interaction.followup.send(msg, ephemeral=True)


class RejectModal(discord.ui.Modal, title="Reject tier revision"):
    note = discord.ui.TextInput(label="Why? (shown to the requester)", style=discord.TextStyle.paragraph,
                                required=False, max_length=300)

    def __init__(self, cog, rid):
        super().__init__()
        self.cog, self.rid = cog, rid

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        msg = await self.cog.review(self.rid, False, str(interaction.user), self.note.value)
        await interaction.followup.send(msg, ephemeral=True)


class Leaderboard(commands.Cog):
    tier = app_commands.Group(name="tier", description="Player tier ratings (Tier 1 = best, Tier 5 = worst)")

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        self.bot.add_dynamic_items(ReviewButton)

    # ------------------------------------------------------------------ helpers
    def tier_name(self, n):
        names = self.db.get("tier_names") or []
        name = names[n - 1] if 0 < n <= len(names) else ""
        return f"{TIER_EMOJI.get(n, '')} Tier {n}" + (f": {name}" if name else "")

    def rating(self, guild_id, user_id):
        r = self.db.q("SELECT tier FROM ratings WHERE guild_id=? AND user_id=?", (guild_id, user_id), one=True)
        return r["tier"] if r else None

    def is_reviewer(self, member):
        if self.bot.is_boss(member) or getattr(member, "guild_permissions", None) and member.guild_permissions.manage_guild:
            return True
        rid = str(self.db.get("tier_reviewer_role_id"))
        return rid.isdigit() and any(r.id == int(rid) for r in getattr(member, "roles", []))

    def review_denied(self, member, rid):
        req = self.db.q("SELECT * FROM tier_requests WHERE id=?", (rid,), one=True)
        if not req:
            return "That request doesn't exist any more."
        if not self.is_reviewer(member):
            return "Only reviewers can approve or reject tier revisions."
        if req["requester_id"] == member.id and not self.bot.is_boss(member):
            return "You can't review your own request. Nice try though."
        return None

    def _set(self, guild_id, user_id, user_name, tier):
        if tier:
            self.db.q("""INSERT INTO ratings(guild_id,user_id,user_name,tier,updated_ts) VALUES(?,?,?,?,?)
                         ON CONFLICT(guild_id,user_id) DO UPDATE SET tier=excluded.tier, user_name=excluded.user_name,
                         updated_ts=excluded.updated_ts""", (guild_id, user_id, user_name, tier, time.time()))
        else:
            self.db.q("DELETE FROM ratings WHERE guild_id=? AND user_id=?", (guild_id, user_id))

    def request_embed(self, req):
        status = {"pending": ("⏳ Pending review", 0xF5A623), "approved": ("✅ Approved", 0x30A46C),
                  "rejected": ("❌ Rejected", 0xE5484D)}.get(req["status"], (req["status"], 0x8B93A3))
        frm = self.tier_name(req["from_tier"]) if req["from_tier"] else "Unranked"
        e = discord.Embed(title=f"Tier revision #{req['id']}: {req['target_name']}", color=status[1],
                          description=f"**{frm}** → **{self.tier_name(req['to_tier'])}**\n\n**Why:** {req['reason']}")
        e.add_field(name="Suggested by", value=req["requester_name"])
        e.add_field(name="Status", value=status[0])
        if req["reviewer"]:
            e.add_field(name="Reviewed by", value=req["reviewer"])
        if req["review_note"]:
            e.add_field(name="Reviewer note", value=req["review_note"], inline=False)
        return e

    # ------------------------------------------------------------------ core actions (also used by the panel)
    async def create_request(self, guild, target, requester, to_tier, reason):
        if not self.db.get("tier_requests_enabled"):
            return None, "Tier revisions are currently closed."
        if target.bot:
            return None, "Bots aren't ranked. We're above that. Literally Tier 0."
        current = self.rating(guild.id, target.id)
        if current == to_tier:
            return None, f"{target.display_name} is already {self.tier_name(to_tier)}."
        if self.db.q("SELECT 1 FROM tier_requests WHERE guild_id=? AND target_id=? AND requester_id=? AND status='pending'",
                     (guild.id, target.id, requester.id), one=True):
            return None, "You already have a pending revision for them. Wait for the verdict."
        n = self.db.q("SELECT COUNT(*) c FROM tier_requests WHERE requester_id=? AND status='pending'", (requester.id,), one=True)["c"]
        if n >= int(self.db.get("tier_max_pending") or 3):
            return None, "You have too many pending revisions. Let the reviewers breathe."
        self.db.q("""INSERT INTO tier_requests(guild_id,target_id,target_name,requester_id,requester_name,from_tier,to_tier,reason,ts)
                     VALUES(?,?,?,?,?,?,?,?,?)""", (guild.id, target.id, str(target), requester.id, str(requester), current,
                                                   to_tier, reason, time.time()))
        rid = self.db.q("SELECT MAX(id) id FROM tier_requests", one=True)["id"]
        req = self.db.q("SELECT * FROM tier_requests WHERE id=?", (rid,), one=True)
        cid = str(self.db.get("tier_review_channel_id"))
        ch = guild.get_channel(int(cid)) if cid.isdigit() else None
        if ch:
            view = discord.ui.View(timeout=None)
            view.add_item(ReviewButton("ok", rid))
            view.add_item(ReviewButton("no", rid))
            try:
                msg = await ch.send(embed=self.request_embed(req), view=view)
                self.db.q("UPDATE tier_requests SET channel_id=?, message_id=? WHERE id=?", (ch.id, msg.id, rid))
            except discord.HTTPException:
                pass
        self.db.log("tier", f"#{rid} {requester} suggests {target} → Tier {to_tier}: {reason[:80]}")
        return rid, None

    async def review(self, rid, approve, reviewer, note=""):
        req = self.db.q("SELECT * FROM tier_requests WHERE id=?", (rid,), one=True)
        if not req or req["status"] != "pending":
            return "That request was already handled."
        status = "approved" if approve else "rejected"
        self.db.q("UPDATE tier_requests SET status=?, reviewer=?, review_note=?, review_ts=? WHERE id=?",
                  (status, reviewer, (note or "").strip()[:300], time.time(), rid))
        if approve:
            self._set(req["guild_id"], req["target_id"], req["target_name"], req["to_tier"])
        req = self.db.q("SELECT * FROM tier_requests WHERE id=?", (rid,), one=True)
        self.db.log("tier", f"#{rid} {status} by {reviewer}")
        # update the review message and tell the requester
        ch = self.bot.get_channel(req["channel_id"]) if req["channel_id"] else None
        if ch:
            try:
                msg = await ch.fetch_message(req["message_id"])
                await msg.edit(embed=self.request_embed(req), view=None)
            except discord.HTTPException:
                pass
        user = self.bot.get_user(req["requester_id"])
        if user:
            verdict = (f"✅ Your tier revision for **{req['target_name']}** ({self.tier_name(req['to_tier'])}) was approved."
                       if approve else f"❌ Your tier revision for **{req['target_name']}** was rejected."
                       + (f"\nReviewer: *{req['review_note']}*" if req["review_note"] else ""))
            try:
                await user.send(verdict)
            except discord.HTTPException:
                pass
        return f"Request #{rid} {status}."

    def set_direct(self, guild_id, user_id, user_name, tier, by, reason):
        current = self.rating(guild_id, user_id)
        self.db.q("""INSERT INTO tier_requests(guild_id,target_id,target_name,requester_id,requester_name,from_tier,to_tier,reason,
                     status,ts,reviewer,review_ts) VALUES(?,?,?,0,?,?,?,?,'direct',?,?,?)""",
                  (guild_id, user_id, user_name, by, current, tier, reason or "-", time.time(), by, time.time()))
        self._set(guild_id, user_id, user_name, tier)
        self.db.log("tier", f"{by} set {user_name} → {'unranked' if not tier else f'Tier {tier}'}")

    def board(self, guild_id):
        rows = self.db.q("SELECT * FROM ratings WHERE guild_id=? ORDER BY tier, user_name COLLATE NOCASE", (guild_id,))
        guild = self.bot.get_guild(guild_id)
        for r in rows:
            m = guild.get_member(r["user_id"]) if guild else None
            r["display"] = m.display_name if m else r["user_name"]
        return {t: [r for r in rows if r["tier"] == t] for t in range(1, 6)}

    # ------------------------------------------------------------------ commands
    @app_commands.command(name="leaderboard", description="Show the tier leaderboard")
    async def leaderboard_cmd(self, inter: discord.Interaction):
        board = self.board(inter.guild.id)
        e = discord.Embed(title=f"🏅 {inter.guild.name} Tier List", color=0xF5A623)
        for t in range(1, 6):
            names = ", ".join(r["display"] for r in board[t]) or "*nobody (yet)*"
            e.add_field(name=self.tier_name(t), value=names[:1024], inline=False)
        e.set_footer(text="Think someone's misranked? /tier suggest. Reviewers decide.")
        await inter.response.send_message(embed=e)

    @tier.command(name="show", description="See someone's tier")
    async def show(self, inter: discord.Interaction, member: discord.Member = None):
        member = member or inter.user
        t = self.rating(inter.guild.id, member.id)
        await inter.response.send_message(f"**{member.display_name}** is {self.tier_name(t) if t else 'unranked'}.",
                                          allowed_mentions=discord.AllowedMentions.none())

    @tier.command(name="suggest", description="Suggest a tier change for someone (a reviewer has to approve it)")
    @app_commands.describe(tier="1 = best, 5 = worst", reason="Why? Reviewers will read this.")
    async def suggest(self, inter: discord.Interaction, member: discord.Member, tier: app_commands.Range[int, 1, 5],
                      reason: app_commands.Range[str, 10, 300]):
        rid, err = await self.create_request(inter.guild, member, inter.user, tier, reason)
        if err:
            await inter.response.send_message(err, ephemeral=True)
            return
        await inter.response.send_message(f"📨 Revision #{rid} submitted: **{member.display_name}** → {self.tier_name(tier)}. "
                                          "You'll get a DM with the verdict.", ephemeral=True)

    @tier.command(name="history", description="See approved/rejected tier changes for someone")
    async def history(self, inter: discord.Interaction, member: discord.Member):
        rows = self.db.q("SELECT * FROM tier_requests WHERE guild_id=? AND target_id=? AND status!='pending' ORDER BY ts DESC LIMIT 10",
                         (inter.guild.id, member.id))
        icon = {"approved": "✅", "rejected": "❌", "direct": "🛠️"}
        text = "\n".join(f"{icon.get(r['status'], '')} <t:{int(r['ts'])}:d> → Tier {r['to_tier'] or '–'} "
                         f"({r['requester_name'] if r['status'] != 'direct' else 'set by ' + (r['reviewer'] or '?')}): {r['reason']}"
                         for r in rows) or "No history. A mystery."
        await inter.response.send_message(f"**Tier history for {member.display_name}**\n{text}"[:2000], ephemeral=True)

    @tier.command(name="set", description="(Reviewers) Set someone's tier directly. Tier 0 removes them.")
    async def set_cmd(self, inter: discord.Interaction, member: discord.Member, tier: app_commands.Range[int, 0, 5],
                      reason: str = ""):
        if not self.is_reviewer(inter.user):
            await inter.response.send_message("Only reviewers can set tiers directly. Use `/tier suggest`.", ephemeral=True)
            return
        self.set_direct(inter.guild.id, member.id, str(member), tier, str(inter.user), reason)
        await inter.response.send_message(f"🛠️ **{member.display_name}** is now {self.tier_name(tier) if tier else 'unranked'}.",
                                          allowed_mentions=discord.AllowedMentions.none())
