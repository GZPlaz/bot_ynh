# SiegeBot for YunoHost

A sarcastic Discord bot for an R6 Siege community: real moderation, R6 fun commands, and a ~~secret~~ **classified**
troll engine for griefing your friends. It comes with a web admin panel on your YunoHost server.

> 📘 **Full installation guide: [INSTALL.md](INSTALL.md)**. Once installed, the admin panel has a complete 📖 Documentation page.

## 1. Create the Discord bot
1. Go to <https://discord.com/developers/applications> → **New Application** → **Bot** → **Reset Token**, and copy the token.
2. On the same **Bot** page, enable **Server Members Intent** and **Message Content Intent**. *(If you skip this, the bot won't log in.)*
3. **OAuth2 → URL Generator**: tick the scopes `bot` and `applications.commands`, then the **Administrator** permission.
   Anti-nuke needs to read the audit log, manage roles and channels, and ban people, so Administrator is the simple route.
   Open the URL and invite the bot.
4. In **Server Settings → Roles**, drag the bot's role **to the top** (just under yours). Anti-nuke can only punish people *below* the bot,
   and trolls can only rename or mute people below it.
5. Get your own user ID: Discord settings → Advanced → Developer Mode, then right-click yourself → *Copy User ID*.

## 2. Install on YunoHost
```bash
sudo yunohost app install https://github.com/GZPlaz/bot_ynh
```
It asks for a domain/path, the bot token and your user ID. The panel is limited to the `admins` group through YunoHost SSO.
You can change who has access under *Users → Permissions*.

Upgrade after pulling changes: `sudo yunohost app upgrade siegebot -u https://github.com/GZPlaz/bot_ynh`
Logs: `sudo journalctl -u siegebot -f`

## Features
**Automod**: a heat-based anti-spam system. Messages, mentions, links, emojis, attachments, line breaks and repeated messages all add heat,
and heat cools over time. Hitting the limit wipes the spammer's recent messages and punishes them, with escalating timeouts for repeat offenders.
There are also filters for banned words, invites, mass mentions, link allowlists and caps, plus auto-warn → auto-timeout.

**Security**:
- **Anti-nuke**: catches untrusted staff or bots that mass-delete or create channels or roles, mass-ban or mass-kick, or spam webhooks.
  It punishes them (quarantine, strip roles, kick or ban), DMs you, and **auto-reverts** the damage: it re-creates deleted channels and roles,
  deletes spam channels and unbans victims.
- It also blocks unauthorized bot additions and reverts dangerous permission grants (Admin, Ban, Manage…).
- **Anti-raid**: detects join floods and turns on raid mode, which kicks, bans, quarantines or times out new joins and can lock the server down.
  It also has a minimum account age and a no-avatar filter.
- **Verification**: a captcha button gate (`/verifypanel`).
- **Quarantine**: strips roles, hides every channel, and restores the roles when released.
- **Lockdown**: per-channel or whole server, and it restores the previous permissions afterwards.
- **Whitelist** of trusted users and roles (`/whitelist`).

**Logging**: message edits and deletes, joins and leaves (with account age), bans, nicknames, roles, timeouts, voice and channel changes,
and a 👻 ghost-ping detector. The troll engine's own actions are kept out of the logs.

**Cases**: every action gets a numbered case. `/warn /modlogs /case /note /clearwarns /timeout /untimeout /purge /kick /ban` (temp-ban with
a `duration` like `7d`) `/unban /softban /slowmode /lock /unlock /lockdown /quarantine /unquarantine /raidmode /nick /userinfo`.
The panel also has a case browser, quarantine and temp-ban lists, and raid/lockdown buttons.

**Fun**: `/operator`, `/strat`, `/clutch` (1v5 simulation, rigged in your favour), `/teams` (splits your voice channel into teams with operators),
`/challenge` (160+ round challenges that never repeat until you've done them all; editable), `/stats` (made up, and it's always on your side), `/roast` (owners get uno-reversed), `/8ball`, `/rate`, `!help`,
plus custom `!commands` and keyword auto-responders that you manage from the panel.

**🏅 Leaderboard**: players are rated Tier 1 (best) to Tier 5 (worst). Anyone can `/tier suggest` a change *with a reason*;
reviewers approve or reject it with buttons in a review channel or in the panel, and the requester gets the verdict by DM. There's a full history,
`/leaderboard`, and an optional public read-only tier list page.

**🧩 Plugins**: the voice clone service is optional. The YunoHost installer asks whether you want it, and you can add or remove it later under
Applications → SiegeBot → Configuration → Plugins.

**Personality**: ping it, reply to it, or say "good bot"/"bad bot" and it answers back with sass. Every line can be edited in the panel.

**Troll engine** (panel → *Troll Control*): add targets and pick their trolls:
reactions 🤡, sPoNgEbOb mocking, phantom "typing...", fake autocorrect, humiliating nicknames, ghost pings, fake bans, 10-second voice-channel
shuffles, 5-second server mutes, 🔊 **voice ambushes** (the bot joins their call and plays a fake footstep, drone, defuser or breach cue,
or the loudest noise in the arsenal), rigged `/stats`, cursed `/operator` picks, and fake "official" report DMs, nickname lock (rename yourself back → new humiliating name), 30–90s micro-timeouts
with absurd reasons, voice disconnects, a hoisted hot-pink role of shame, a typing sniper ("nobody asked" before they hit enter),
parrot mode, ghost-ping sprees across 5 channels, 📸 **photo spam** (your uploaded pictures, or their own profile picture), 🧨 emoji bombs spelling B-O-T-F-R-A-G,
📦 message teleporting, 📌 pins of shame, and voice chaos: 6-second deafens, a "dying mic" mute stutter, a 20-second solo voice
jail, a robot voice yelling fake callouts in their call, and potato mode (their channel drops to 8 kbps for 2 minutes).
Robot-voice chaos: every victim gets their own personal robot voice, which **reads their text messages aloud** while they're in voice.
A **join announcer** greets them ("Please lower your expectations"), a **sports commentator** narrates the moment they type "dead",
"rip" or "my bad", and the robot can **read their stats to the whole call**. Trolls fire at random based on
*chance × chaos*, from a timed loop, or on demand from the panel. Bot owners **and server admins** (configurable) can also type secret `,,` commands in chat (owners stay immune to them, and admin use is logged); the bot deletes
them instantly (`,,help` DMs you the list).
The 🚨 **Panic button** turns everything off and restores everyone's nicknames.

**Soundboard** (panel → *Soundboard*): ships with an **R6 sound pack** of 59 clips from MyInstants' "r6" search
(nitro cell, Lion scan, defuser alarm, Fuze cluster charge…), plus 12 built-in synthesized sounds.
⚠️ The pack is mostly ripped game audio, so **keep this repository private**. There are pure noise ones (air horn, alarm, siren, distorted square wave,
sad trombone) and fake cues (footsteps, drone, defuser, breach, gunfire, reinforcement, glass). They're all original, not game audio.
You can upload your own clips, play them in any call or follow a specific person into theirs, set the volume up to 1000% (it clips and distorts
past 100%), import sounds by pasting links (e.g. a MyInstants search page grabs every sound on it, downloaded to your server only), make the robot voice (espeak-ng) say anything in someone's call, or use `,,tts @user <text>`, `,,blast @user`, `,,ambush @user` and `,,sound @user air_horn 3` in chat.

## 🧬 Opt-in voice clones
Friends who *want* to be cloned run `/voiceclone optin`, choose who may use their voice (bot owners only, or everyone), and upload
10–30 s of **their own** voice with `/voiceclone sample` (a Discord voice message works). After that, `/mimic @friend <text>`,
`,,clone @friend <text>` or the Soundboard page make their AI voice say anything in a call. `/voiceclone optout` deletes the sample instantly.
Friends too lazy to upload? Upload their clip in the panel (Soundboard → Voice clones). The bot DMs them the clip with
**Allow** / **Delete** buttons, and their clone activates the moment they tap Allow. Unapproved samples are deleted after 7 days.

Cloning needs a heavy AI model (Chatterbox, MIT-licensed, about 4 GB RAM; a GPU makes it fast), so it runs as a **separate optional service**.
That can be on your YunoHost box if it has the RAM, or on a gaming PC:
```bash
cd clone_server
python3 -m venv venv && venv/bin/pip install -r requirements.txt
CLONE_TOKEN=pick-a-long-secret venv/bin/python server.py --host 0.0.0.0 --port 8765 --device cuda   # or cpu
```
Then enter `http://<that-machine>:8765` and the token in the panel under **Robot Voice & Clones**, and hit *Test clone service*.
Chatterbox adds an inaudible watermark to everything it generates. On CPU, expect roughly 10–40 s per sentence.
`clone_server/siegebot-clone.service` is an example systemd unit.

## Layout
`manifest.toml`, `scripts/`, `conf/` are the YunoHost package. `sources/siegebot/` holds the bot and panel (discord.py + aiohttp + SQLite in `/home/yunohost.app/siegebot`).
