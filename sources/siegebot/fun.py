import hashlib
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from .defaults import ATTACKERS, DEFENDERS
from .util import fill

CHALLENGES = [
    "Pistols only. Yes, even on attack.", "No drones. Pure vibes and fear.", "Everyone must melee at least once or you're benched.",
    "Shields only (Monty, Blitz, Fuze, Clash, Recruit). Form the turtle.", "Nobody may crouch. Ever.",
    "You can only talk in callouts from a nature documentary.", "Last alive has to plant/defend alone, no help.",
    "Everyone picks the operator to their left's main.", "All of you rappel the same window. Together. Holding hands.",
    "Hip-fire only. ADS is for cowards.", "No reinforcements on defense. Walls are a social construct.",
    "Every kill must be followed by a tea-bag or you owe the team a round.",
]

CLUTCH_EVENTS = [
    "drops in on the defuser with 0:{t} left...", "hears footsteps above...", "pre-fires a corner. Nobody there. Embarrassing.",
    "throws a nade. It bounces back.", "gets a clean headshot! 1 down.", "swings wide like a maniac...",
    "trips on barbed wire.", "hides behind a shield guy's shield (it's an enemy's).", "hears a drone. Shoots it. Feels powerful.",
    "gets a sick double through a soft wall!", "peeks the same angle for the third time.", "runs past the bomb site entirely.",
]

RANKS = ["Copper V", "Bronze III", "Silver II", "Gold I", "Platinum", "Emerald", "Diamond", "Champion"]


def fake_stats(bot, member):
    """Deterministic fake stats. Owners are gods, fake_stats targets are tragic."""
    seed = int(hashlib.md5(str(member.id).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    t = bot.db.target(member.id) if bot.db.get("trolls_enabled") else None
    if bot.is_boss(member):
        kd, wr, hs, rank = rng.uniform(2.5, 4.2), rng.uniform(70, 90), rng.uniform(55, 75), "Champion (obviously)"
    elif t and "fake_stats" in t["trolls"]:
        kd, wr, hs, rank = rng.uniform(0.05, 0.35), rng.uniform(3, 18), rng.uniform(0.1, 4), "Copper V (hardstuck)"
    else:
        kd, wr, hs, rank = rng.uniform(0.7, 1.4), rng.uniform(40, 60), rng.uniform(20, 45), rng.choice(RANKS)
    return {"kd": kd, "wr": wr, "hs": hs, "rank": rank, "seed": seed}


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
        st = fake_stats(self.bot, member)
        kd, wr, hs, rank = st["kd"], st["wr"], st["hs"], st["rank"]
        rng = random.Random(st["seed"])
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

    @app_commands.command(description="Simulate a 1v5 clutch. Results may be rigged.")
    async def clutch(self, inter: discord.Interaction, member: discord.Member = None):
        member = member or inter.user
        events = random.sample(CLUTCH_EVENTS, k=4)
        if self.bot.is_boss(member):
            won = True
        elif self.trolled(member, "fake_stats"):
            won = False
        else:
            won = random.random() < 0.35
        lines = [f"**{member.display_name}** is alone vs 5. Round on the line."]
        for i, ev in enumerate(events):
            lines.append(f"`{['0:45', '0:30', '0:15', '0:05'][i]}` {member.display_name} {ev.replace('{t}', str(random.randint(5, 30)))}")
        lines.append(f"\n🏆 **ACE. CLUTCH. LEGEND.** {member.mention} wins the round!" if won else
                     f"\n💀 {member.mention} died. The enemy didn't even need to aim. GG go next.")
        await inter.response.send_message("\n".join(lines))

    @app_commands.command(description="Split the people in your voice channel into two random teams with operators")
    async def teams(self, inter: discord.Interaction):
        if not inter.user.voice or not inter.user.voice.channel:
            await inter.response.send_message("Join a voice channel first. I can't split invisible people.", ephemeral=True)
            return
        players = [m for m in inter.user.voice.channel.members if not m.bot]
        if len(players) < 2:
            await inter.response.send_message("You need friends for this. At least one. 😬", ephemeral=True)
            return
        random.shuffle(players)
        half = (len(players) + 1) // 2
        a, b = players[:half], players[half:]
        atk, dfn = random.sample(ATTACKERS, k=len(a)), random.sample(DEFENDERS, k=len(b))
        e = discord.Embed(title="⚔️ Teams", color=0xF5A623)
        e.add_field(name="🔵 Attack", value="\n".join(f"{m.display_name}: **{o}**" for m, o in zip(a, atk)))
        e.add_field(name="🟠 Defense", value="\n".join(f"{m.display_name}: **{o}**" for m, o in zip(b, dfn)) or "nobody")
        e.set_footer(text="Swap sides every 3 rounds. Complaints go to /dev/null.")
        await inter.response.send_message(embed=e)

    @app_commands.command(description="Get a random challenge for the next round")
    async def challenge(self, inter: discord.Interaction):
        await inter.response.send_message(f"🎯 **Challenge:** {random.choice(CHALLENGES)}")

    @app_commands.command(description="Rate anything out of 10")
    async def rate(self, inter: discord.Interaction, thing: str):
        score = int(hashlib.md5(thing.lower().encode()).hexdigest(), 16) % 11
        await inter.response.send_message(f"I rate **{discord.utils.escape_markdown(thing)}** a solid **{score}/10**.",
                                          allowed_mentions=discord.AllowedMentions.none())
