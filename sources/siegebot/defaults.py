"""Default settings and all the snark. Everything here is editable from the admin panel."""

ATTACKERS = ["Sledge", "Thatcher", "Ash", "Thermite", "Twitch", "Montagne", "Glaz", "Fuze", "Blitz", "IQ",
             "Buck", "Blackbeard", "Capitão", "Hibana", "Jackal", "Ying", "Zofia", "Dokkaebi", "Lion", "Finka",
             "Maverick", "Nomad", "Gridlock", "Nøkk", "Amaru", "Kali", "Iana", "Ace", "Zero", "Flores", "Osa",
             "Sens", "Grim", "Brava", "Ram", "Deimos", "Striker", "Rauora"]
DEFENDERS = ["Smoke", "Mute", "Castle", "Pulse", "Doc", "Rook", "Kapkan", "Tachanka", "Jäger", "Bandit",
             "Frost", "Valkyrie", "Caveira", "Echo", "Mira", "Lesion", "Ela", "Vigil", "Maestro", "Alibi",
             "Clash", "Kaid", "Mozzie", "Warden", "Goyo", "Wamai", "Oryx", "Melusi", "Aruni", "Thunderbird",
             "Thorn", "Azami", "Solis", "Fenrir", "Tubarão", "Sentry", "Skopós"]

TROLL_TYPES = ["react", "mock", "typing", "correct", "nickname", "ghost_ping", "fake_ban", "voice_shuffle",
               "voice_mute", "fake_stats", "cursed_ops", "dm_report", "sound_ambush", "noise_blast",
               "nick_lock", "micro_timeout", "voice_kick", "role_of_shame", "typing_sniper", "parrot", "ping_spree",
               "voice_deafen", "voice_stutter", "voice_jail", "fake_callout", "potato_mode"]

TROLL_DESCRIPTIONS = {
    "react": "Randomly reacts to their messages with clowns, salt and skulls",
    "mock": "Replies to their messages in sPoNgEbOb CaSe",
    "typing": "Starts 'typing...' right after they talk, then says nothing",
    "correct": "\"Corrects\" their messages with a much worse version",
    "nickname": "Periodically renames them to something humiliating (auto-saved original)",
    "ghost_ping": "Pings them in a random channel and instantly deletes it",
    "fake_ban": "Announces they've been banned. They have not. (Probably.)",
    "voice_shuffle": "Moves them to a random voice channel for 10 seconds mid-round",
    "voice_mute": "Server-mutes them for 5 seconds. Right during the callout.",
    "fake_stats": "/stats always shows them a tragic K/D",
    "cursed_ops": "/operator only gives them cursed loadouts",
    "dm_report": "DMs them a totally official 'report received' notice",
    "sound_ambush": "Bot sneaks into their voice call and plays a fake cue (footsteps, drone, defuser...)",
    "noise_blast": "Bot joins their voice call and blasts the loudest noise in the arsenal",
    "nick_lock": "Once renamed, changing their nickname back instantly gets them a NEW humiliating one",
    "micro_timeout": "Real 30-90 second timeout with an absurd reason. Always mid-argument.",
    "voice_kick": "Disconnects them from voice. Mid-clutch, ideally.",
    "role_of_shame": "Hoisted hot-pink role like '🤡 Certified Bottom Frag' for 30 minutes, shown at the top of the member list",
    "typing_sniper": "The moment they start typing, the bot replies 'nobody asked' before they can send",
    "parrot": "For 3 minutes the bot repeats every single thing they say",
    "ping_spree": "Ghost-pings them in up to 5 channels in a row. Unread badges everywhere.",
    "voice_deafen": "Server-deafens them for 6 seconds. They miss every callout.",
    "voice_stutter": "Mutes/unmutes them rapidly for ~8 seconds so their mic sounds like it's dying",
    "voice_jail": "Drags them alone into a locked '🔒 Timeout Corner' channel for 20 seconds, then back",
    "fake_callout": "Bot joins their call and a robot voice yells fake callouts ('TWO IN BASEMENT!')",
    "potato_mode": "Drops their voice channel to 8 kbps for 2 minutes. Everyone sounds like a potato.",
}

SASS_LINES = [
    "Oh look, {user} pinged me. My day was going so well.",
    "I'm a bot, {user}. I don't have feelings. But if I did, you'd have hurt them.",
    "You rang? I was busy calculating how many times you've died to a Frost mat. The number is large.",
    "{user}, I have read every message in this server. I'm not mad. I'm disappointed.",
    "Yes, {user}? Make it quick, I'm rendering a montage of your teamkills.",
    "Ping me again and I'll tell everyone your rank.",
    "I'd explain it to you, {user}, but I left my crayons in the other channel.",
    "Did you just @ me like I'm your Doc? I'm not healing that ego.",
    "Fun fact: I process 10,000 messages a second and yours was still the worst.",
    "{user}, I'm legally required to respond. Here is my response: no.",
    "You have the confidence of a 1v5 Recruit and the results of one too.",
    "Beep boop. That's bot for 'please go play the game'.",
    "Oh, it's you. Did you finally get a kill? Proud of you. Genuinely. *slow clap*",
    "I've seen better aim from a Tachanka turret with no one on it.",
    "My therapist told me to set boundaries. This is one. Hello though.",
    "{user}, you remind me of a reinforced wall: loud, in the way, and Thermite would fix you.",
    "Error 404: interest in this conversation not found.",
    "If I had a dollar for every time you pinged me, I could afford a better community.",
    "Hold on, let me drone out this conversation first... nope, nothing useful in here.",
    "You know the plant has to go *on* the bomb site, right {user}? Just checking.",
]

GOOD_BOT_LINES = ["I know.", "Finally, some recognition. Put it in writing.", "Stop, I'm blushing in binary.",
                  "Correct. Unlike your last 40 rotates."]
BAD_BOT_LINES = ["Bold words from someone who reinforces the wrong wall every round.",
                 "I'll remember that. I remember everything, {user}.", "Noted. Logged. Filed under 'cope'.",
                 "Says the person who died to a Kapkan trap. Twice. Same trap."]

STRATS = [
    "Everyone goes Blitz. No questions. Run it down main hallway.",
    "All five rappel the same window and pray.",
    "Defense: everyone hides in the bathroom and holds hands.",
    "Shotguns only. If you see a wall, it's your enemy now.",
    "Spawn peek. Every round. Until the heat death of the universe.",
    "Pick Tachanka, plant the turret in the middle of the site, protect him with your lives.",
    "Silent round: no comms, only drone pings and vibes.",
    "Melee-only round. Knife culture is back.",
    "One person carries the defuser, the other four are bodyguards. Formation: diamond.",
    "Full roam. Nobody on site. Ever. We are the hunters now.",
    "Throw every utility in the first 10 seconds then go AFK and see what happens.",
    "Crouch-walk the entire round. Never stand. Standing is for the weak.",
]

ROASTS = [
    "{target} has the game sense of a drone stuck under a couch.",
    "{target}'s crosshair placement is somewhere near their ankles. Consistent though.",
    "{target} doesn't pre-fire, they post-die.",
    "{target} has 2,000 hours and still asks 'where is that?' every round.",
    "{target} plays Doc just to heal their own ego.",
    "{target}'s rotate holes have rotate holes.",
    "If {target} was a gadget, they'd be a Yokai drone: annoying, small, and easily shot.",
    "{target} calls 'one shot' about enemies at full HP.",
    "{target} thinks 'clutch' is just a pedal in a car.",
]

EIGHT_BALL = ["Absolutely.", "Nope.", "Ask again after you win a round.", "Signs point to you whiffing.",
              "As certain as Ash rushing.", "My sources say get good first.", "Doubtful. Very doubtful.",
              "Yes, but you won't like it.", "The drone says no.", "Outlook spicy."]

CURSED_OPS = ["Tachanka. Turret only. You may not leave the turret.", "Recruit with a shield. Good luck.",
              "Blitz, but you have to sprint everywhere.", "Montagne. Shield extended. Entire round.",
              "Glaz, but you're only allowed to hip-fire.", "Clash on attack. Don't ask how.",
              "Doc, but you must heal the enemy if you see one.", "Caveira, and you have to interrogate a teammate."]

NICKNAMES = ["Bottom Frag", "Recoil Enjoyer", "Silver Forever", "Spawn Peek Victim", "Wall Reinforcer",
             "Frost Mat Magnet", "Drone Fodder", "Tachanka Main", "Defuser Dropper", "1 HP Hero",
             "Rotate Hole Enjoyer", "Team Flash Pro", "Clutch? Never Heard Of It", "Mute Jammer Victim",
             "Professional Spectator", "Hostage Damager", "Lost in Basement", "Copper Champion"]

REACTIONS = ["🤡", "🧂", "💀", "🗑️", "🫵", "😬", "🐌", "🧻", "📉", "🥶"]

FAKE_BAN_LINES = [
    "🔨 **{target} has been banned.** Reason: crimes against the team (14 counts of team-flashing).",
    "🔨 **{target} has been permanently banned** for excessive spawn-peek related deaths.",
    "🔨 **{target} has been banned.** Reason: refused to drone. Ever.",
]
FAKE_BAN_REVEAL = ["...jk. For now. 👀", "Just kidding. Unless? 😈", "lol no. But think about what you did."]

DM_REPORTS = [
    "📨 **Siege Integrity Department (totally real)**\nA report was received regarding your gameplay. "
    "Category: *Disrespecting the Hostage*. Our review team has concluded: you are bad. No further action.",
    "📨 **Notice of Skill Review (very official)**\nYour recent performance has been flagged as 'concerning'. "
    "Please practice in Terrorist Hunt for 400 hours and try again.",
]

SNIPER_LINES = [
    "Nobody asked, {user}.", "Whatever you're typing: wrong.", "Put the keyboard down, {user}.",
    "I can see you typing. Reconsider.", "Before you send that: no.", "Typing that long? Must be an excuse for last round.",
    "Let me guess: 'it was lag'.", "{user} is typing... and the server collectively sighs.",
]

TIMEOUT_REASONS = [
    "Skill issue", "Spawn peeked one too many times", "Crimes against the hostage", "Excessive coping",
    "Reinforced the wrong wall (again)", "Team-flashed the entire squad", "Said 'he's one shot' about a full-HP enemy",
    "Bottom fragged with Recruit", "Being Copper in spirit",
]

FAKE_CALLOUTS = [
    "Two in basement! Two in basement!", "He's one shot! He's one shot! Push now!", "Behind you! Behind you!",
    "Defuser is planted! Go go go!", "Roamer in garage, rotate!", "They're flanking left, watch left!",
    "Breach on main wall, get off the wall!", "Nitro cell! Move!", "I'm dead, it was Dave's fault.",
    "Enemy drone in your room. Shoot it. Shoot it now.", "He's tea bagging me. Avenge me.",
]

JAIL_NAMES = ["🔒 Timeout Corner", "🔒 Think About Your Rotates", "🔒 Copper Containment Unit", "🔒 Spawn Peek Jail"]

SHAME_ROLE_NAMES = [
    "🤡 Certified Bottom Frag", "🧂 Professional Coper", "📉 Negative K/D Club", "🐌 Slowest Rotate Alive",
    "🗑️ Spawn Peek Victim", "🥉 Copper V (Hardstuck)", "🙈 Has Never Droned", "💀 Dies First Every Round",
]

CORRECTIONS = {
    "i": "I (a noob)", "good": "mid", "nice": "lucky", "gg": "gg (I got carried)", "win": "lose",
    "won": "got carried", "kill": "assist", "headshot": "body shot", "easy": "difficult for me",
    "clutch": "choke", "lol": "lol (crying inside)", "pro": "bronze", "carry": "get carried",
}

DEFAULTS = {
    "token": "",
    "prefix": "!",
    "status_text": "you whiff every peek",
    "sass_enabled": True,
    "sass_lines": SASS_LINES,
    "good_bot_lines": GOOD_BOT_LINES,
    "bad_bot_lines": BAD_BOT_LINES,
    "strats": STRATS,
    "roasts": ROASTS,
    "eight_ball": EIGHT_BALL,
    # moderation
    "mod_enabled": True,
    "banned_words": [],
    "filter_invites": True,
    "filter_caps": False,
    "caps_min_length": 12,
    "mass_mention_limit": 5,
    "link_filter": False,
    "link_allowlist": ["tenor.com", "giphy.com", "youtube.com", "youtu.be", "twitch.tv", "imgur.com",
                       "ubisoft.com", "r6.tracker.network", "discord.com", "cdn.discordapp.com", "media.discordapp.net"],
    # heat-based anti-spam: every message adds heat, heat cools down over time
    "heat_enabled": True,
    "heat_threshold": 100,
    "heat_decay": 12,
    "heat_message": 10,
    "heat_mention": 12,
    "heat_link": 12,
    "heat_attachment": 10,
    "heat_emoji": 3,
    "heat_newline": 3,
    "heat_duplicate": 30,
    "heat_action": "timeout",
    "max_warnings": 3,
    "timeout_minutes": 10,
    "log_channel_id": "",
    "welcome_channel_id": "",
    "welcome_message": "Welcome {mention} to {server}! Don't spawn peek. (You will spawn peek.)",
    "exempt_role_ids": [],
    "whitelist_ids": [],
    # anti-nuke
    "antinuke_enabled": True,
    "antinuke_window": 30,
    "nuke_channel_delete": 3,
    "nuke_channel_create": 6,
    "nuke_role_delete": 3,
    "nuke_role_create": 6,
    "nuke_ban": 3,
    "nuke_kick": 4,
    "nuke_webhook": 3,
    "antinuke_punishment": "quarantine",
    "antinuke_restore": True,
    "antibot_add": True,
    "protect_dangerous_perms": True,
    # anti-raid
    "antiraid_enabled": True,
    "raid_joins": 8,
    "raid_seconds": 15,
    "raid_action": "kick",
    "raid_auto_lockdown": False,
    "raid_duration_minutes": 10,
    "min_account_age_days": 0,
    "young_account_action": "kick",
    "no_avatar_action": "none",
    # verification gate
    "verify_enabled": False,
    "verified_role_id": "",
    # quarantine / lockdown state
    "quarantine_role_id": "",
    "lockdown_state": {},
    # event logging
    "event_log_channel_id": "",
    "log_messages": True,
    "log_members": True,
    "log_roles": True,
    "log_voice": True,
    "log_server": True,
    "ghost_ping_detector": True,
    # soundboard
    "sound_volume": 150,
    "sound_max_seconds": 20,
    # trolls
    "trolls_enabled": True,
    "chaos": 1.0,
    "troll_loop_minutes": 15,
    "cursed_ops": CURSED_OPS,
    "nicknames": NICKNAMES,
    "reactions": REACTIONS,
    "fake_ban_lines": FAKE_BAN_LINES,
    "fake_ban_reveal": FAKE_BAN_REVEAL,
    "dm_reports": DM_REPORTS,
    "corrections": CORRECTIONS,
    "sniper_lines": SNIPER_LINES,
    "timeout_reasons": TIMEOUT_REASONS,
    "shame_role_names": SHAME_ROLE_NAMES,
    "shame_minutes": 30,
    "fake_callouts": FAKE_CALLOUTS,
    "jail_names": JAIL_NAMES,
    "shame_roles": {},     # guild_id -> role_id
    "shame_expiry": {},    # "guild:user" -> ts
}
