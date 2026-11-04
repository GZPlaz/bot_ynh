import asyncio
import logging
import random
import time

import discord
from discord.ext import commands

from .util import chance, fill

log = logging.getLogger("siegebot")


class SiegeBot(commands.Bot):
    def __init__(self, db, owner_ids):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=lambda b, m: [], intents=intents, help_command=None)
        self.db = db
        self.owner_id_set = set(owner_ids)
        self.started_at = time.time()
        self._sass_cooldown = {}

    def is_boss(self, user):
        return user.id in self.owner_id_set

    async def setup_hook(self):
        from . import fun, moderation, trolls
        await self.add_cog(moderation.Moderation(self))
        await self.add_cog(fun.Fun(self))
        await self.add_cog(trolls.Trolls(self))

    async def on_ready(self):
        log.info("Logged in as %s", self.user)
        self.db.log("bot", f"Logged in as {self.user} in {len(self.guilds)} server(s)")
        await self.refresh_presence()
        for g in self.guilds:
            try:
                self.tree.copy_global_to(guild=g)
                await self.tree.sync(guild=g)
            except discord.HTTPException as e:
                log.warning("Slash sync failed for %s: %s", g, e)

    async def refresh_presence(self):
        text = self.db.get("status_text") or ""
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=text))

    async def on_member_join(self, member):
        ch_id = self.db.get("welcome_channel_id")
        ch = member.guild.get_channel(int(ch_id)) if str(ch_id).isdigit() else None
        if ch:
            await ch.send(fill(self.db.get("welcome_message"), mention=member.mention,
                               user=member.display_name, server=member.guild.name))

    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        mod = self.get_cog("Moderation")
        if mod and await mod.check_message(message):
            return  # message was removed by moderation

        trolls = self.get_cog("Trolls")
        if trolls and self.is_boss(message.author) and message.content.startswith(",,"):
            await trolls.hidden_command(message)
            return

        if await self.handle_custom_command(message):
            return
        if await self.handle_sass(message):
            return
        await self.handle_responders(message)
        if trolls:
            await trolls.on_target_message(message)

    async def handle_custom_command(self, message):
        prefix = self.db.get("prefix") or "!"
        if not message.content.startswith(prefix):
            return False
        name, _, args = message.content[len(prefix):].partition(" ")
        row = self.db.q("SELECT * FROM commands WHERE name=? AND enabled=1", (name.lower(),), one=True)
        if not row:
            if name.lower() == "help":
                names = [r["name"] for r in self.db.q("SELECT name FROM commands WHERE enabled=1")]
                listing = ", ".join(prefix + n for n in names) or "none, the admin is lazy"
                await message.channel.send(f"Custom commands: {listing}\nAlso try the `/` commands. Or don't. I'm a bot, not a cop.")
                return True
            return False
        self.db.q("UPDATE commands SET uses=uses+1 WHERE name=?", (row["name"],))
        target = message.mentions[0].mention if message.mentions else message.author.mention
        await message.channel.send(fill(row["response"], user=message.author.display_name, mention=message.author.mention,
                                        server=message.guild.name, args=args, target=target),
                                   allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
        return True

    async def handle_sass(self, message):
        if not self.db.get("sass_enabled"):
            return False
        lower = message.content.lower()
        replied_to_me = (message.reference and isinstance(message.reference.resolved, discord.Message)
                         and message.reference.resolved.author == self.user)
        pinged = self.user in message.mentions
        if "good bot" in lower or "bad bot" in lower:
            key = "good_bot_lines" if "good bot" in lower else "bad_bot_lines"
        elif pinged or replied_to_me:
            key = "sass_lines"
        else:
            return False
        now = time.time()
        if now - self._sass_cooldown.get(message.author.id, 0) < 3:
            return True
        self._sass_cooldown[message.author.id] = now
        lines = self.db.get(key) or ["..."]
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.6, 1.8))  # dramatic pause
        await message.reply(fill(random.choice(lines), user=message.author.display_name,
                                 mention=message.author.mention, server=message.guild.name),
                            mention_author=False)
        return True

    async def handle_responders(self, message):
        lower = message.content.lower()
        for r in self.db.q("SELECT * FROM responders"):
            trig = r["trigger"].lower()
            hit = lower == trig if r["match"] == "exact" else trig in lower
            if hit and chance(r["chance"]):
                await message.channel.send(fill(r["response"], user=message.author.display_name,
                                                mention=message.author.mention, server=message.guild.name),
                                           allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
                return

    async def send_log(self, guild, text):
        self.db.log("mod", f"[{guild.name}] {text}")
        ch_id = self.db.get("log_channel_id")
        ch = guild.get_channel(int(ch_id)) if str(ch_id).isdigit() else None
        if ch:
            try:
                await ch.send(text, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
