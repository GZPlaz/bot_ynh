import hashlib
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from .defaults import ATTACKERS, DEFENDERS
from .util import fill

RANKS = ["Copper V", "Bronze III", "Silver II", "Gold I", "Platinum", "Emerald", "Diamond", "Champion"]


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def trolled(self, user, kind):
        if not self.db.get("trolls_enabled"):
            return False
        t = self.db.target(user.id)
        return bool(t and kind in t["trolls"])

    @app_commands.command(description="Pick a random operator for you")
    async def operator(self, inter: discord.Interaction, side: Literal["attack", "defense"]):
        if self.trolled(inter.user, "cursed_ops"):
            pick = random.choice(self.db.get("cursed_ops"))
            await inter.response.send_message(f"🎲 The dice have spoken, {inter.user.mention}: **{pick}**")
            return
        pick = random.choice(ATTACKERS if side == "attack" else DEFENDERS)
        await inter.response.send_message(f"🎲 {inter.user.mention}, you're playing **{pick}**. No rerolls. Cope.")

    @app_commands.command(description="Get a strat guaranteed to work (it will not work)")
    async def strat(self, inter: discord.Interaction):
        await inter.response.send_message(f"📋 **Strat:** {random.choice(self.db.get('strats'))}")

    @app_commands.command(description="Look up someone's (extremely accurate) stats")
    async def stats(self, inter: discord.Interaction, member: discord.Member = None):
        member = member or inter.user
        seed = int(hashlib.md5(str(member.id).encode()).hexdigest(), 16)
        rng = random.Random(seed)
        if self.bot.is_boss(member):
            kd, wr, hs, rank = rng.uniform(2.5, 4.2), rng.uniform(70, 90), rng.uniform(55, 75), "Champion (obviously)"
        elif self.trolled(member, "fake_stats"):
            kd, wr, hs, rank = rng.uniform(0.05, 0.35), rng.uniform(3, 18), rng.uniform(0.1, 4), "Copper V (hardstuck)"
        else:
            kd, wr, hs, rank = rng.uniform(0.7, 1.4), rng.uniform(40, 60), rng.uniform(20, 45), rng.choice(RANKS)
        e = discord.Embed(title=f"📊 Stats for {member.display_name}", color=0xF5A623)
        e.add_field(name="Rank", value=rank)
        e.add_field(name="K/D", value=f"{kd:.2f}")
        e.add_field(name="Win rate", value=f"{wr:.1f}%")
        e.add_field(name="Headshot %", value=f"{hs:.1f}%")
        e.add_field(name="Teamkills", value=str(rng.randint(3, 400)))
        e.add_field(name="Hostages harmed", value=str(rng.randint(0, 99)))
        e.set_footer(text="Source: trust me bro")
        await inter.response.send_message(embed=e)

    @app_commands.command(description="Roast someone")
    async def roast(self, inter: discord.Interaction, member: discord.Member):
        if member == self.bot.user:
            await inter.response.send_message("Nice try. I'm unroastable. I'm made of pure confidence and Python.")
            return
        if self.bot.is_boss(member):
            member = inter.user  # uno reverse
        await inter.response.send_message(fill(random.choice(self.db.get("roasts")), target=member.mention))

    @app_commands.command(name="8ball", description="Ask the magic 8-ball")
    async def eightball(self, inter: discord.Interaction, question: str):
        await inter.response.send_message(f"🎱 *{discord.utils.escape_markdown(question)}*\n**{random.choice(self.db.get('eight_ball'))}**")

    @app_commands.command(description="Rate anything out of 10")
    async def rate(self, inter: discord.Interaction, thing: str):
        score = int(hashlib.md5(thing.lower().encode()).hexdigest(), 16) % 11
        await inter.response.send_message(f"I rate **{discord.utils.escape_markdown(thing)}** a solid **{score}/10**.",
                                          allowed_mentions=discord.AllowedMentions.none())
