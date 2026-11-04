# SiegeBot installation guide

This guide takes you from nothing to a running bot with its admin panel on YunoHost, plus the optional voice-clone service.
Allow about 15 minutes (plus however long the clone model takes to download, if you want clones).

- [1. Requirements](#1-requirements)
- [2. Create the Discord application](#2-create-the-discord-application)
- [3. Invite the bot to your server](#3-invite-the-bot-to-your-server)
- [4. Install on YunoHost](#4-install-on-yunohost)
- [5. First-time setup in the panel](#5-first-time-setup-in-the-panel)
- [6. Optional: voice-clone service](#6-optional-voice-clone-service)
- [7. Upgrading, backups and removal](#7-upgrading-backups-and-removal)
- [8. Running without YunoHost (development)](#8-running-without-yunohost-development)
- [9. Troubleshooting](#9-troubleshooting)

---

## 1. Requirements

| | Minimum |
|---|---|
| YunoHost | 12.0 or newer (Debian 12) |
| RAM for the bot | ~150 MB |
| Disk | ~300 MB (Python packages, ffmpeg, sounds) |
| A domain/subdomain | for the admin panel, e.g. `bot.example.com` or `example.com/siegebot` |
| Discord | a server where you have **Manage Server** (you'll be adding a bot) |

The installer pulls in its system packages: `python3-venv`, `ffmpeg` (playing sounds), `libopus0` (Discord voice) and `espeak-ng` (robot voice).

## 2. Create the Discord application

1. Go to <https://discord.com/developers/applications> and click **New Application**. Name it whatever you like (that's the bot's name).
2. Open the **Bot** tab:
   - Click **Reset Token**, then **copy the token**. You need it in step 4. Treat it like a password; anyone with it controls your bot.
   - Under **Privileged Gateway Intents**, enable **Server Members Intent** and **Message Content Intent**. ⚠️ Without these the bot can't log in.
   - Optional: turn off **Public Bot** so only you can invite it.
3. Get your own Discord user ID: in Discord, **User Settings → Advanced → Developer Mode** on, then right-click your name → **Copy User ID**.
   Owner IDs unlock the secret commands and make you immune to every troll.

## 3. Invite the bot to your server

1. In the developer portal: **OAuth2 → URL Generator**.
2. Scopes: tick **`bot`** and **`applications.commands`**.
3. Bot permissions: tick **Administrator**.
   Anti-nuke, quarantine, lockdown, voice jail and potato mode all need management permissions, and Administrator is the simplest reliable option.
4. Open the generated URL, pick your server, and authorize.
5. In Discord: **Server Settings → Roles**. Drag the bot's role **to the top**, just under your own.
   The bot can only moderate, rename, mute or quarantine people whose highest role is *below* its own.

## 4. Install on YunoHost

### Option A: command line (SSH into your server)

```bash
sudo yunohost app install https://github.com/GZPlaz/bot_ynh
```

You'll be asked for:

| Question | What to enter |
|---|---|
| Domain | where the admin panel lives |
| Path | e.g. `/siegebot` (or `/` on a dedicated subdomain) |
| Who can access the panel | keep **admins**. The panel controls moderation and lists the secret trolls. |
| Discord bot token | from step 2 |
| Your Discord user ID(s) | from step 2; separate several with commas |
| Install the voice clone service? | **No** unless you want AI voice clones right away *and* the server has ~4 GB free RAM and 6 GB disk. You can add it later as a plugin ([section 6](#6-optional-voice-clone-service)). |

### Option B: web admin

**Applications → Install**, scroll to the bottom to **Install a custom app**, paste `https://github.com/GZPlaz/bot_ynh` and answer the same questions.

When it finishes, the bot comes online in Discord within a few seconds and the panel is at `https://<domain><path>`, behind the YunoHost login.

> YunoHost will warn that this is a custom app not from the official catalog. That's expected.

## 5. First-time setup in the panel

1. **Dashboard**: should show **ONLINE**. If it shows an error, see [Troubleshooting](#9-troubleshooting).
2. **Automod**: choose a **Mod log channel** (punishments and security alerts).
3. **Logging**: choose an **Event log channel** (edits, deletes, joins, voice…).
4. **Security**: add trusted moderators (user or role IDs) to the **whitelist** so anti-nuke never touches them.
   Check the anti-raid numbers suit your server size.
5. Optional **verification gate**: see the in-panel documentation (📖 Documentation → Security → Verification).
6. **🏅 Leaderboard settings**: pick a **review channel** (where tier suggestions get Approve/Reject buttons) and optionally a reviewer role.
   Turn on the **public leaderboard page** if friends should see the tier list without logging in.
7. **Troll Control**: add your first target. 😈

Everything else is explained on the panel's **📖 Documentation** page. Its command, troll and settings lists are generated from the code, so they're always current.

## 6. Optional: voice-clone service

Voice clones are **opt-in**: members run `/voiceclone optin` and upload their own voice sample.
Generating a cloned voice needs an AI model (Chatterbox, MIT-licensed), which is too heavy to bundle with the bot, so it runs as a separate service the bot calls over HTTP.

| Where to run it | Needs | Speed |
|---|---|---|
| Same YunoHost server | ~4 GB free RAM, ~6 GB disk | 10–40 s per sentence (CPU) |
| A gaming PC with an NVIDIA GPU | ~4 GB VRAM, ~6 GB disk | about 1–3 s per sentence |

### 6a. On the YunoHost server (CPU): the easy way, as a plugin

If you answered **yes** during install, it's already done. Otherwise you can add it (or remove it) whenever you like:

- **Web admin:** Applications → **SiegeBot** → **Configuration** → **Plugins** → toggle **Voice clone service** → **Save**. It takes 10+ minutes.
- **Command line:**
  ```bash
  sudo yunohost app config set siegebot main.plugins.clone_service -v 1   # install
  sudo yunohost app config set siegebot main.plugins.clone_service -v 0   # uninstall (frees the space)
  ```

The plugin runs on `127.0.0.1` with an auto-generated token and the bot is connected to it automatically, with nothing to configure.
The first start downloads the AI model (~2 GB) in the background; follow it with `sudo journalctl -u siegebot-clone -f`.
Check it on the panel's **🧩 Plugins** page (*Test connection*). Upgrades keep the plugin installed; backups skip its multi-GB files and restores reinstall them.

### 6a (manual alternative). Without the plugin system

```bash
git clone https://github.com/GZPlaz/bot_ynh /tmp/bot_ynh
sudo mkdir -p /opt/siegebot-clone
sudo cp -r /tmp/bot_ynh/clone_server/* /opt/siegebot-clone/
cd /opt/siegebot-clone
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
sudo chown -R siegebot:siegebot /opt/siegebot-clone
```

Edit `siegebot-clone.service` and set `CLONE_TOKEN` to a long random string (`openssl rand -hex 24` makes one). Then:

```bash
sudo cp /opt/siegebot-clone/siegebot-clone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now siegebot-clone
sudo journalctl -u siegebot-clone -f
```

The first start downloads the model (~2 GB). Wait for it to start listening before testing.
In the panel, under **Robot Voice & Clones**, set **URL** to `http://127.0.0.1:8765` and **Token** to your `CLONE_TOKEN`, then press **Test clone service** on the Soundboard page.

> If you installed the app more than once, the system user is the app ID (`siegebot__2`, …). Use that in `chown` and in the unit file.

### 6b. On a PC with a GPU (Linux or Windows)

```bash
git clone https://github.com/GZPlaz/bot_ynh
cd bot_ynh/clone_server
python3 -m venv venv
# Linux: venv/bin/pip …   Windows: venv\Scripts\pip …
venv/bin/pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
venv/bin/pip install -r requirements.txt
```

Start it. Linux:

```bash
CLONE_TOKEN=your-long-secret venv/bin/python server.py --host 0.0.0.0 --port 8765 --device cuda
```

Windows (PowerShell):

```powershell
$env:CLONE_TOKEN="your-long-secret"; venv\Scripts\python server.py --host 0.0.0.0 --port 8765 --device cuda
```

The YunoHost server must be able to reach the PC on port 8765:
- **Same home network:** use the PC's LAN IP (e.g. `http://192.168.1.50:8765`) and allow port 8765 in the PC's firewall.
- **YunoHost is a VPS / different network:** don't expose the port to the internet. Put both machines on a private network such as Tailscale or WireGuard and use that IP.

The service speaks plain HTTP and is protected only by the token, so keep it on a private network.

## 7. Upgrading, backups and removal

```bash
# upgrade to the latest version on GitHub (settings and data are kept)
sudo yunohost app upgrade siegebot -u https://github.com/GZPlaz/bot_ynh

# backup / restore (includes the database, sounds and voice samples)
sudo yunohost backup create --apps siegebot
sudo yunohost backup restore <backup_name> --apps siegebot

# remove
sudo yunohost app remove siegebot
```

Data lives in `/home/yunohost.app/siegebot/`: `siegebot.db` (all settings, cases, targets…), `sounds/` (built-in and uploaded) and `voices/` (opt-in clone samples).

## 8. Running without YunoHost (development)

```bash
cd sources
python3 -m venv venv
venv/bin/pip install -r requirements.txt
DATA_DIR=./data PORT=8085 DISCORD_TOKEN=xxx OWNER_IDS=1234567890 venv/bin/python -m siegebot
```

Open <http://127.0.0.1:8085>. ⚠️ Without YunoHost there is **no login** on the panel. It only listens on localhost, so don't put it behind a public reverse proxy without adding authentication.
You also need `ffmpeg`, `libopus0` and `espeak-ng` installed for voice features.

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| Dashboard: `LoginFailure: Improper token` | Reset the token in the developer portal and paste it in **General**. |
| Dashboard: `PrivilegedIntentsRequired` | Enable both intents (step 2), then **Restart** on the dashboard. |
| Slash commands missing | Restart the bot, then reload Discord with Ctrl+R. The invite must include the `applications.commands` scope (step 3). |
| "Discord said no" / can't rename or mute someone | The bot's role must be above theirs (step 3.5). Nobody can act on the server owner. |
| Bot joins voice but is silent | Check the panel's **Logs** page. Make sure `ffmpeg` and `libopus0` are installed. |
| Robot voice silent | `sudo apt install espeak-ng` |
| Panel shows 502 Bad Gateway | The service is down: `sudo systemctl status siegebot` and `sudo journalctl -u siegebot -n 100`. |
| Clone "service unreachable" | Is it running? Can the YunoHost box reach that IP and port? Does the token match? |

Logs: `sudo journalctl -u siegebot -f`
