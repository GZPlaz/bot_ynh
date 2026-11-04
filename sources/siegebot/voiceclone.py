"""Opt-in voice clones. Only the person themselves can opt in and upload their sample; opting out deletes it."""
import asyncio
import os
import tempfile
import time
import wave

import discord
from discord import app_commands
from discord.ext import commands

CONSENT_TEXT = (
    "**🎙️ Voice clone: opt-in**\n"
    "If you agree, you'll upload a short clip of **your own voice** (`/voiceclone sample`). The bot can then generate AI speech "
    "that sounds like you and play it in this server's voice channels.\n\n"
    "• Your sample is stored on the server owner's machine and only used for this.\n"
    "• Generated audio is AI-made and watermarked as such.\n"
    "• `/voiceclone optout` deletes your sample instantly, any time.\n\n"
    "Who may make you say things?"
)


PENDING_DAYS = 7


async def convert_sample(src, dst):
    """Any audio -> 24 kHz mono wav, max 30 s. Returns duration in seconds (0 if unreadable)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-y", "-i", src, "-ac", "1", "-ar", "24000", "-t", "30", dst,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()
    try:
        with wave.open(dst) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, FileNotFoundError, EOFError):
        return 0


class ApprovalView(discord.ui.View):
    """Persistent buttons on the 'someone uploaded your voice' DM. Acts only on the clicking user's own pending sample."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Allow: bot owners only", style=discord.ButtonStyle.primary, custom_id="siegebot:clone_ok_owners")
    async def ok_owners(self, inter, _):
        await self.cog.resolve_pending(inter, "owners")

    @discord.ui.button(label="Allow: anyone in the server", style=discord.ButtonStyle.success, custom_id="siegebot:clone_ok_everyone")
    async def ok_everyone(self, inter, _):
        await self.cog.resolve_pending(inter, "everyone")

    @discord.ui.button(label="No, delete it", style=discord.ButtonStyle.danger, custom_id="siegebot:clone_deny")
    async def deny(self, inter, _):
        await self.cog.resolve_pending(inter, None)


class ConsentView(discord.ui.View):
    def __init__(self, cog, user):
        super().__init__(timeout=180)
        self.cog, self.user = cog, user

    async def _agree(self, inter, scope):
        self.cog.db.q("""INSERT INTO voice_clones(user_id,user_name,scope,consent_ts) VALUES(?,?,?,?)
                         ON CONFLICT(user_id) DO UPDATE SET scope=excluded.scope, consent_ts=excluded.consent_ts,
                         user_name=excluded.user_name""", (self.user.id, str(self.user), scope, time.time()))
        self.cog.db.log("clone", f"{self.user} opted in (scope: {scope})")
        await inter.response.edit_message(
            content=f"✅ Opted in ({'everyone' if scope == 'everyone' else 'bot owners only'}). Now run `/voiceclone sample` "
                    "and attach 10-30 seconds of you talking clearly (no music, no background game audio).", view=None)

    @discord.ui.button(label="Agree: bot owners only", style=discord.ButtonStyle.primary)
    async def owners(self, inter, _):
        await self._agree(inter, "owners")

    @discord.ui.button(label="Agree: anyone in the server", style=discord.ButtonStyle.success)
    async def everyone(self, inter, _):
        await self._agree(inter, "everyone")

    @discord.ui.button(label="No thanks", style=discord.ButtonStyle.secondary)
    async def cancel(self, inter, _):
        await inter.response.edit_message(content="No worries. Nothing was saved.", view=None)


class VoiceClone(commands.Cog):
    group = app_commands.Group(name="voiceclone", description="Opt in to (or out of) having an AI clone of your voice")

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.dir = os.path.join(bot.data_dir, "voices")
        os.makedirs(self.dir, exist_ok=True)

    async def cog_load(self):
        self.bot.add_view(ApprovalView(self))

    # ------------------------------------------------------------------ admin-uploaded samples (need the person's OK)
    def expire_pending(self):
        for row in self.db.q("SELECT * FROM pending_clones WHERE ts < ?", (time.time() - PENDING_DAYS * 86400,)):
            self.drop_pending(row["user_id"])
            self.db.log("clone", f"Pending voice sample for {row['user_name']} expired (never approved)")

    def drop_pending(self, user_id):
        row = self.db.q("SELECT * FROM pending_clones WHERE user_id=?", (user_id,), one=True)
        if row and row["sample"] and os.path.exists(row["sample"]):
            os.remove(row["sample"])
        self.db.q("DELETE FROM pending_clones WHERE user_id=?", (user_id,))

    async def submit_for_approval(self, member, src_path, uploaded_by):
        """Convert an admin-uploaded clip and ask `member` to approve it. Returns a status string."""
        self.expire_pending()
        out = os.path.join(self.dir, f"pending_{member.id}.wav")
        secs = await convert_sample(src_path, out)
        if secs < 5:
            if os.path.exists(out):
                os.remove(out)
            return "That clip is too short or unreadable (need at least 5 seconds of them talking)."
        self.db.q("""INSERT OR REPLACE INTO pending_clones(user_id,user_name,sample,uploaded_by,ts,dm_status)
                     VALUES(?,?,?,?,?,?)""", (member.id, str(member), out, uploaded_by, time.time(), "sending"))
        self.db.log("clone", f"{uploaded_by} uploaded a {secs:.0f}s voice sample for {member}, waiting for their approval")
        return await self.send_request(member)

    async def send_request(self, member):
        row = self.db.q("SELECT * FROM pending_clones WHERE user_id=?", (member.id,), one=True)
        if not row:
            return "Nothing pending for them."
        text = (f"🎙️ **{member.guild.name}** wants to make an AI voice clone of you, using the clip attached "
                f"(uploaded by the server's bot admin).\n\n"
                "If you allow it, people can make an AI version of your voice say things in that server's voice channels. "
                "It's labelled as AI when used, and `/voiceclone optout` deletes it any time.\n"
                f"**Nothing happens unless you press Allow.** Ignore this and it's deleted in {PENDING_DAYS} days.")
        try:
            await member.send(text, file=discord.File(row["sample"], filename="your_voice_sample.wav"), view=ApprovalView(self))
            status = "DM sent"
        except discord.HTTPException:
            status = "DMs closed"
        self.db.q("UPDATE pending_clones SET dm_status=? WHERE user_id=?", (status, member.id))
        if status == "DM sent":
            return f"Sent {member.display_name} a DM to approve. Their clone activates as soon as they press Allow."
        return (f"{member.display_name} has DMs closed. Ask them to run /voiceclone status in the server; "
                "the approve buttons are there too.")

    async def resolve_pending(self, inter, scope):
        uid = inter.user.id
        row = self.db.q("SELECT * FROM pending_clones WHERE user_id=?", (uid,), one=True)
        if not row:
            await inter.response.edit_message(content="This request expired or was already handled.", view=None, attachments=[])
            return
        if scope is None:
            self.drop_pending(uid)
            self.db.log("clone", f"{inter.user} declined the uploaded voice sample (deleted)")
            await inter.response.edit_message(content="🗑️ Deleted. No clone of you exists.", view=None, attachments=[])
            return
        final = os.path.join(self.dir, f"{uid}.wav")
        os.replace(row["sample"], final)
        self.db.q("""INSERT INTO voice_clones(user_id,user_name,scope,consent_ts,sample) VALUES(?,?,?,?,?)
                     ON CONFLICT(user_id) DO UPDATE SET scope=excluded.scope, consent_ts=excluded.consent_ts,
                     sample=excluded.sample, user_name=excluded.user_name""", (uid, str(inter.user), scope, time.time(), final))
        self.db.q("DELETE FROM pending_clones WHERE user_id=?", (uid,))
        self.db.log("clone", f"{inter.user} approved their voice clone (scope: {scope})")
        await inter.response.edit_message(
            content=f"✅ Approved ({'anyone' if scope == 'everyone' else 'bot owners only'}). `/voiceclone optout` deletes it any time.",
            view=None, attachments=[])

    def record(self, user_id):
        return self.db.q("SELECT * FROM voice_clones WHERE user_id=?", (user_id,), one=True)

    @group.command(name="optin", description="Agree to let the bot clone your voice")
    async def optin(self, inter: discord.Interaction):
        await inter.response.send_message(CONSENT_TEXT, view=ConsentView(self, inter.user), ephemeral=True)

    @group.command(name="sample", description="Upload 10-30s of YOUR OWN voice (after /voiceclone optin)")
    async def sample(self, inter: discord.Interaction, audio: discord.Attachment):
        if not self.record(inter.user.id):
            await inter.response.send_message("Run `/voiceclone optin` first.", ephemeral=True)
            return
        if audio.size > 10 * 1024 * 1024 or not ((audio.content_type or "").startswith(("audio/", "video/"))
                                                 or audio.filename.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".opus", ".webm", ".flac"))):
            await inter.response.send_message("Send an audio file under 10 MB (a Discord voice message works too).", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        out = os.path.join(self.dir, f"{inter.user.id}.wav")
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(audio.filename)[1] or ".ogg", delete=False) as tmp:
            await audio.save(tmp.name)
        try:
            secs = await convert_sample(tmp.name, out)
        finally:
            os.remove(tmp.name)
        if secs < 5:
            if os.path.exists(out):
                os.remove(out)
            await inter.followup.send("That clip is too short or unreadable. I need at least 5 seconds of you talking.",
                                      ephemeral=True)
            return
        self.db.q("UPDATE voice_clones SET sample=? WHERE user_id=?", (out, inter.user.id))
        self.db.log("clone", f"{inter.user} uploaded a {secs:.0f}s voice sample")
        await inter.followup.send(f"✅ Got {secs:.0f}s of your voice. Try `/voiceclone test` while in a voice channel.",
                                  ephemeral=True)

    @group.command(name="optout", description="Delete your voice sample and opt out")
    async def optout(self, inter: discord.Interaction):
        self.delete(inter.user.id)
        await inter.response.send_message("🗑️ Your voice sample and consent are deleted. You're un-cloned.", ephemeral=True)

    def delete(self, user_id):
        self.drop_pending(user_id)
        row = self.record(user_id)
        if row and row["sample"] and os.path.exists(row["sample"]):
            os.remove(row["sample"])
        self.db.q("DELETE FROM voice_clones WHERE user_id=?", (user_id,))
        if row:
            self.db.log("clone", f"{row['user_name']} voice clone deleted")

    @group.command(name="status", description="See your voice clone status")
    async def status(self, inter: discord.Interaction):
        self.expire_pending()
        pending = self.db.q("SELECT * FROM pending_clones WHERE user_id=?", (inter.user.id,), one=True)
        if pending:
            await inter.response.send_message(
                "🎙️ The bot admin uploaded a voice sample of you (attached) and wants your OK to make a voice clone. "
                "Nothing happens unless you press Allow.",
                file=discord.File(pending["sample"], filename="your_voice_sample.wav"), view=ApprovalView(self), ephemeral=True)
            return
        row = self.record(inter.user.id)
        if not row:
            text = "You haven't opted in. Your voice is safe from me. For now."
        else:
            text = (f"Opted in <t:{int(row['consent_ts'])}:R>, usable by **{'everyone' if row['scope'] == 'everyone' else 'bot owners'}**. "
                    f"Sample: {'✅' if row['sample'] else '❌ not uploaded'}. Used {row['uses']} time(s). `/voiceclone optout` to delete.")
        await inter.response.send_message(text, ephemeral=True)

    @group.command(name="test", description="Hear your own clone in your voice channel")
    async def test(self, inter: discord.Interaction, text: str = "Hello. I am the superior version of you. I never spawn peek."):
        await self._speak(inter, inter.user, text)

    @app_commands.command(description="Make someone's opted-in voice clone say something in your voice channel")
    async def mimic(self, inter: discord.Interaction, member: discord.Member, text: app_commands.Range[str, 1, 300]):
        row = self.record(member.id)
        if not row or not row["sample"]:
            await inter.response.send_message(f"{member.display_name} hasn't opted in to voice cloning. "
                                              "They can with `/voiceclone optin`.", ephemeral=True)
            return
        if row["scope"] != "everyone" and inter.user.id != member.id and not self.bot.is_boss(inter.user):
            await inter.response.send_message(f"{member.display_name} only lets the bot owners use their voice.", ephemeral=True)
            return
        await self._speak(inter, member, text)

    async def _speak(self, inter, member, text):
        if not inter.user.voice or not inter.user.voice.channel:
            await inter.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        await inter.response.send_message(f"🗣️ Generating AI voice of **{member.display_name}** (opted in)... this can take a bit.")
        result = await self.bot.get_cog("Soundboard").clone_speak(inter.user.voice.channel, member.id, text)
        await inter.edit_original_response(content=f"🗣️ AI voice of **{member.display_name}** (opted in): *{discord.utils.escape_markdown(text)}*"
                                           + ("" if result.startswith("said") else f"\n⚠️ {result}"))
