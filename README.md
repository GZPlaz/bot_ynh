# SiegeBot for YunoHost

A sarcastic Discord bot for an R6 Siege community: real moderation, R6 fun commands, and a ~~secret~~ **classified**
troll engine for griefing your friends. It comes with a web admin panel on your YunoHost server.

## 1. Create the Discord bot
1. Go to <https://discord.com/developers/applications> → **New Application** → **Bot** → **Reset Token**, and copy the token.
2. On the same **Bot** page, enable **Server Members Intent** and **Message Content Intent**. *(If you skip this, the bot won't log in.)*
3. **OAuth2 → URL Generator**: tick the scopes `bot` and `applications.commands`. Then tick the permissions *Manage Nicknames, Moderate Members,
   Kick Members, Ban Members, Manage Messages, Read Message History, Send Messages, Add Reactions, Move Members, Mute Members*.
   Open the URL and invite the bot.
4. In **Server Settings → Roles**, drag the bot's role **above** your friends' roles. Otherwise it can't rename or mute them.
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
**Moderation**: banned words, invite filter, anti-spam, caps filter, auto-warn → auto-timeout, a mod log channel, a welcome message,
and `/warn /warnings /clearwarns /timeout /purge /kick /ban`.

**Fun**: `/operator`, `/strat`, `/stats` (made up, and it's always on your side), `/roast` (owners get uno-reversed), `/8ball`, `/rate`, `!help`,
plus custom `!commands` and keyword auto-responders that you manage from the panel.

**Personality**: ping it, reply to it, or say "good bot"/"bad bot" and it answers back with sass. Every line can be edited in the panel.

**Troll engine** (panel → *Troll Control*): add targets and pick their trolls:
reactions 🤡, sPoNgEbOb mocking, phantom "typing...", fake autocorrect, humiliating nicknames, ghost pings, fake bans, 10-second voice-channel
shuffles, 5-second server mutes, rigged `/stats`, cursed `/operator` picks, and fake "official" report DMs. Trolls fire at random based on
*chance × chaos*, from a timed loop, or on demand from the panel. As an owner you can also type secret `,,` commands in chat; the bot deletes
them instantly (`,,help` DMs you the list).
The 🚨 **Panic button** turns everything off and restores everyone's nicknames.

## Layout
`manifest.toml`, `scripts/`, `conf/` are the YunoHost package. `sources/siegebot/` holds the bot and panel (discord.py + aiohttp + SQLite in `/home/yunohost.app/siegebot`).
