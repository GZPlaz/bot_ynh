"""Admin panel. Sits behind YunoHost SSO (nginx); only listens on 127.0.0.1."""
import os
import re
import time
from datetime import datetime
from urllib.parse import quote, urlparse

import discord
from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import sounds as sound_lib
from .defaults import TROLL_DESCRIPTIONS, TROLL_TYPES
from .trolls import ACTIONS

# section -> (title, intro, [(key, type, label, help[, choices])])
JOIN_ACTIONS = ["none", "timeout", "kick", "ban", "quarantine"]
SECTIONS = {
    "general": ("General", "Core bot settings.", [
        ("token", "secret", "Bot token", "Leave blank to keep the current one. Saving restarts the bot."),
        ("owner_ids", "str", "Owner Discord IDs", "Comma separated. Owners can use the secret ,, commands and are immune to everything."),
        ("prefix", "str", "Custom command prefix", ""),
        ("status_text", "str", "'Watching ...' status", ""),
        ("welcome_channel_id", "channel", "Welcome channel", ""),
        ("welcome_message", "str", "Welcome message", "Placeholders: {mention} {user} {server}"),
    ]),
    "moderation": ("Automod", "Message filtering. Members with Manage Messages, owners, the server owner and whitelisted users/roles are skipped.", [
        ("mod_enabled", "bool", "Automod enabled", ""),
        ("log_channel_id", "channel", "Mod log channel", "Punishments, cases and security alerts go here."),
        ("banned_words", "lines", "Banned words", "One per line, whole-word match."),
        ("filter_invites", "bool", "Delete Discord invite links", ""),
        ("mass_mention_limit", "int", "Mass mention limit", "Delete + warn when a message pings this many users/roles. 0 = off."),
        ("link_filter", "bool", "Only allow links from the allowlist", ""),
        ("link_allowlist", "lines", "Allowed link domains", "Subdomains included."),
        ("filter_caps", "bool", "Delete ALL CAPS messages", ""),
        ("caps_min_length", "int", "Caps filter minimum letters", ""),
        ("max_warnings", "int", "Warnings before auto-timeout", "0 disables auto-timeout."),
        ("timeout_minutes", "int", "Base timeout length (minutes)", "Repeat spam offenders get this × strike count."),
        ("exempt_role_ids", "lines", "Exempt role IDs", "One per line."),
        ("heat_enabled", "bool", "🔥 Heat anti-spam", "Every message adds heat; heat cools over time. Hitting the limit nukes their recent messages and punishes."),
        ("heat_threshold", "int", "Heat limit", ""),
        ("heat_decay", "float", "Heat cooldown per second", ""),
        ("heat_action", "choice", "Punishment at heat limit", "", ["warn", "timeout", "kick", "ban", "quarantine"]),
        ("heat_message", "float", "Heat: per message", ""),
        ("heat_mention", "float", "Heat: per mention", ""),
        ("heat_link", "float", "Heat: per link", ""),
        ("heat_attachment", "float", "Heat: per attachment", ""),
        ("heat_emoji", "float", "Heat: per emoji", ""),
        ("heat_newline", "float", "Heat: per line break", ""),
        ("heat_duplicate", "float", "Heat: repeated message", ""),
    ]),
    "security": ("Security", "Anti-nuke, anti-raid and verification. Give the bot Administrator (or View Audit Log + Manage Roles/Channels + Ban/Kick) and put its role near the top.", [
        ("whitelist_ids", "lines", "Trusted user/role IDs (whitelist)", "Bypass anti-nuke and automod. Bot owners and the server owner are always trusted."),
        ("antinuke_enabled", "bool", "🛡️ Anti-nuke", "Punishes untrusted staff/bots that mass-delete channels/roles, mass-ban/kick or spam webhooks."),
        ("antinuke_window", "int", "Anti-nuke window (seconds)", ""),
        ("nuke_channel_delete", "int", "Limit: channel deletions", ""),
        ("nuke_channel_create", "int", "Limit: channel creations", ""),
        ("nuke_role_delete", "int", "Limit: role deletions", ""),
        ("nuke_role_create", "int", "Limit: role creations", ""),
        ("nuke_ban", "int", "Limit: bans", ""),
        ("nuke_kick", "int", "Limit: kicks", ""),
        ("nuke_webhook", "int", "Limit: webhook creations", ""),
        ("antinuke_punishment", "choice", "Anti-nuke punishment", "", ["quarantine", "strip", "kick", "ban"]),
        ("antinuke_restore", "bool", "Auto-revert nukes", "Re-creates deleted channels/roles, deletes spam channels/roles, unbans mass-banned users."),
        ("antibot_add", "bool", "Kick bots added by untrusted members", ""),
        ("protect_dangerous_perms", "bool", "Block dangerous permission grants", "Reverts Admin/Ban/Manage perms given to roles or members by untrusted users."),
        ("antiraid_enabled", "bool", "🚨 Anti-raid", "Detects join floods and turns on raid mode."),
        ("raid_joins", "int", "Raid: joins...", ""),
        ("raid_seconds", "int", "...within seconds", ""),
        ("raid_action", "choice", "Action on joins during raid mode", "", JOIN_ACTIONS),
        ("raid_duration_minutes", "int", "Raid mode lasts (minutes)", ""),
        ("raid_auto_lockdown", "bool", "Lock all channels when a raid is detected", ""),
        ("min_account_age_days", "int", "Minimum account age (days)", "0 = off."),
        ("young_account_action", "choice", "Action for too-young accounts", "", JOIN_ACTIONS),
        ("no_avatar_action", "choice", "Action for accounts with no avatar", "", JOIN_ACTIONS),
        ("verify_enabled", "bool", "✅ Verification gate", "Run /verifypanel in a channel to post the captcha button."),
        ("verified_role_id", "role", "Verified role", "Make @everyone unable to see channels and give this role access."),
    ]),
    "logging": ("Logging", "Server event logs (like an audit trail you can actually read). Troll activity is automatically kept out.", [
        ("event_log_channel_id", "channel", "Event log channel", ""),
        ("log_messages", "bool", "Message edits & deletions", ""),
        ("log_members", "bool", "Joins, leaves, bans, nicknames, timeouts", ""),
        ("log_roles", "bool", "Role changes", ""),
        ("log_voice", "bool", "Voice joins/leaves/moves", ""),
        ("log_server", "bool", "Channel create/delete", ""),
        ("ghost_ping_detector", "bool", "👻 Ghost ping detector", "Calls people out for deleting a message that pinged someone."),
    ]),
    "personality": ("Personality", "What the bot says. Placeholders: {user} {mention} {server} {target} {op}.", [
        ("sass_enabled", "bool", "Sarcastic replies when pinged/replied to", ""),
        ("sass_lines", "lines", "Sass lines", "One per line."),
        ("good_bot_lines", "lines", "'good bot' replies", ""),
        ("bad_bot_lines", "lines", "'bad bot' replies", ""),
        ("roasts", "lines", "/roast lines", "Use {target}."),
        ("strats", "lines", "/strat lines", ""),
        ("eight_ball", "lines", "/8ball answers", ""),
    ]),
    "voice": ("Robot Voice & Clones", "Lines for the robot voice trolls, and the optional voice-clone service. "
              "Clones only exist for people who ran /voiceclone optin themselves; you can't upload anyone's voice from here.", [
        ("commentator_lines", "lines", "Death commentator lines", "Use {user}."),
        ("announcer_lines", "lines", "Voice join announcer lines", "Use {user}."),
        ("fake_callouts", "lines", "Fake voice callouts", ""),
        ("clone_api_url", "str", "Voice clone service URL (override)", "Leave empty to use the YunoHost plugin. Set it to use another machine, e.g. a GPU PC: http://192.168.1.50:8765"),
        ("clone_api_token", "secret", "Voice clone service token (override)", "Only needed with the URL override; same as CLONE_TOKEN on that machine. Leave blank to keep."),
        ("clone_exaggeration", "float", "Clone expressiveness", "0.25 = calm, 0.5 = normal, 1.0+ = unhinged."),
    ]),
    "leaderboard": ("Leaderboard settings", "Tier 1 is the best, Tier 5 the worst. Anyone can suggest a revision with a reason; reviewers approve or reject.", [
        ("tier_names", "lines", "Tier names (exactly 5 lines, Tier 1 first)", ""),
        ("tier_requests_enabled", "bool", "Allow /tier suggest", ""),
        ("tier_review_channel_id", "channel", "Review channel", "New suggestions are posted here with Approve/Reject buttons."),
        ("tier_reviewer_role_id", "role", "Reviewer role", "Can approve/reject and /tier set. Bot owners and Manage Server can always review."),
        ("tier_max_pending", "int", "Max pending suggestions per person", ""),
        ("public_leaderboard", "bool", "Public leaderboard page", "Read-only tier list at <your panel URL>/public/leaderboard with no login. Shows only names and tiers."),
    ]),
    "trollcfg": ("Troll Arsenal", "The content used by the secret trolls.", [
        ("nicknames", "lines", "Humiliating nicknames", "Max 32 characters each."),
        ("reactions", "lines", "Reaction emojis", ""),
        ("cursed_ops", "lines", "Cursed /operator picks", ""),
        ("fake_ban_lines", "lines", "Fake ban announcements", "Use {target}."),
        ("fake_ban_reveal", "lines", "Fake ban 'jk' follow-ups", ""),
        ("dm_reports", "lines", "Fake report DMs", ""),
        ("corrections", "dict", "Autocorrect replacements", "word = replacement, one per line."),
        ("sniper_lines", "lines", "Typing-sniper lines", "Use {user}."),
        ("timeout_reasons", "lines", "Micro-timeout reasons", ""),
        ("shame_role_names", "lines", "Role-of-shame names", "Max 100 characters."),
        ("shame_minutes", "int", "Role of shame lasts (minutes)", ""),
        ("jail_names", "lines", "Voice jail channel names", ""),
    ]),
}
SECTIONS = {k: (t, i, [dict(zip(("key", "typ", "label", "help", "choices"), f + (None,) * (5 - len(f)))) for f in fs])
            for k, (t, i, fs) in SECTIONS.items()}


def create_app(db, ctl, data_dir, base_path):
    base = "/" + base_path.strip("/") if base_path.strip("/") else ""
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
                      autoescape=select_autoescape())
    env.filters["ts"] = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")

    def bot():
        b = ctl.bot
        return b if b and b.is_ready() else None

    def channels():
        b = bot()
        if not b:
            return []
        return [(str(c.id), f"{g.name} / #{c.name}") for g in b.guilds for c in g.text_channels]

    def roles():
        b = bot()
        if not b:
            return []
        return [(str(r.id), f"{g.name} / @{r.name}") for g in b.guilds for r in g.roles if not r.is_default() and not r.managed]

    def render(name, request, **ctx):
        ctx.update(base=base, path=request.path, bot=bot(), ctl=ctl, sections=SECTIONS, flash=request.query.get("msg"))
        return web.Response(text=env.get_template(name).render(**ctx), content_type="text/html")

    def go(where, msg=None):
        raise web.HTTPFound(base + where + ("?msg=" + quote(msg) if msg else ""))

    @web.middleware
    async def csrf(request, handler):
        if request.method == "POST":
            origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
            if urlparse(origin).netloc != request.host:
                raise web.HTTPForbidden(text="Cross-site request blocked.")
        return await handler(request)

    routes = web.RouteTableDef()

    @routes.get("/")
    async def dashboard(request):
        stats = {
            "commands": db.q("SELECT COUNT(*) c FROM commands", one=True)["c"],
            "responders": db.q("SELECT COUNT(*) c FROM responders", one=True)["c"],
            "cases": db.q("SELECT COUNT(*) c FROM cases", one=True)["c"],
            "targets": db.q("SELECT COUNT(*) c FROM targets", one=True)["c"],
        }
        b = bot()
        uptime = int(time.time() - b.started_at) if b else 0
        sec = b.get_cog("Security") if b else None
        guilds = [{"g": g, "raid": sec.raid_active(g),
                   "locked": len((db.get("lockdown_state") or {}).get(str(g.id), {}))} for g in (b.guilds if b else [])]
        return render("dashboard.html", request, stats=stats, uptime=uptime,
                      logs=db.q("SELECT * FROM logs ORDER BY id DESC LIMIT 15"),
                      trolls_enabled=db.get("trolls_enabled"), chaos=db.get("chaos"), guilds=guilds)

    @routes.post("/bot/{action}")
    async def bot_action(request):
        action = request.match_info["action"]
        if action == "restart":
            await ctl.start()
            go("/", "Bot restarting...")
        if action == "stop":
            await ctl.stop()
            go("/", "Bot stopped.")
        if action == "panic":
            b = bot()
            n = await b.get_cog("Trolls").panic() if b else 0
            db.set("trolls_enabled", False)
            go("/", f"Panic button pressed. Trolls off, {n} nickname(s) restored. Your secret is safe.")
        raise web.HTTPNotFound()

    # ---------------- generic settings
    @routes.get("/settings/{section}")
    async def settings_get(request):
        sec = request.match_info["section"]
        if sec not in SECTIONS:
            raise web.HTTPNotFound()
        title, intro, fields = SECTIONS[sec]
        values = db.all_settings()
        values["owner_ids"] = ",".join(str(i) for i in ctl.owner_ids())
        return render("form.html", request, sec=sec, title=title, intro=intro, fields=fields, values=values,
                      channels=channels(), roles=roles())

    @routes.post("/settings/{section}")
    async def settings_post(request):
        sec = request.match_info["section"]
        if sec not in SECTIONS:
            raise web.HTTPNotFound()
        form = await request.post()
        restart = False
        for f in SECTIONS[sec][2]:
            key, typ = f["key"], f["typ"]
            raw = form.get(key, "")
            if typ == "bool":
                val = key in form
            elif typ == "int":
                val = int(raw or 0)
            elif typ == "float":
                val = float(raw or 0)
            elif typ == "lines":
                val = [l.strip() for l in raw.splitlines() if l.strip()]
            elif typ == "dict":
                val = {}
                for line in raw.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        val[k.strip()] = v.strip()
            elif typ == "choice":
                if raw not in f["choices"]:
                    continue
                val = raw
            elif typ == "secret":
                if not raw.strip():
                    continue
                val, restart = raw.strip(), key == "token"
            else:
                val = raw.strip()
            if key == "owner_ids":
                restart = restart or val != ",".join(str(i) for i in ctl.owner_ids())
            db.set(key, val)
        if restart:
            await ctl.start()
        elif bot() and sec == "general":
            await bot().refresh_presence()
        go(f"/settings/{sec}", "Saved." + (" Bot restarting." if restart else ""))

    # ---------------- custom commands
    @routes.get("/commands")
    async def commands_get(request):
        return render("commands.html", request, rows=db.q("SELECT * FROM commands ORDER BY name"),
                      responders=db.q("SELECT * FROM responders ORDER BY id"), prefix=db.get("prefix"))

    @routes.post("/commands/add")
    async def commands_add(request):
        f = await request.post()
        name = f.get("name", "").strip().lower().lstrip(db.get("prefix") or "!").split(" ")[0]
        if name and f.get("response", "").strip():
            db.q("INSERT INTO commands(name,response) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET response=excluded.response",
                 (name, f["response"].strip()))
        go("/commands", f"Command '{name}' saved.")

    @routes.post("/commands/{name}/toggle")
    async def commands_toggle(request):
        db.q("UPDATE commands SET enabled=1-enabled WHERE name=?", (request.match_info["name"],))
        go("/commands")

    @routes.post("/commands/{name}/delete")
    async def commands_delete(request):
        db.q("DELETE FROM commands WHERE name=?", (request.match_info["name"],))
        go("/commands", "Deleted.")

    @routes.post("/responders/add")
    async def responders_add(request):
        f = await request.post()
        if f.get("trigger", "").strip() and f.get("response", "").strip():
            db.q("INSERT INTO responders(trigger,response,match,chance) VALUES(?,?,?,?)",
                 (f["trigger"].strip(), f["response"].strip(), "exact" if f.get("match") == "exact" else "contains",
                  max(0.0, min(1.0, float(f.get("chance") or 100) / 100))))
        go("/commands", "Auto-responder added.")

    @routes.post("/responders/{id}/delete")
    async def responders_delete(request):
        db.q("DELETE FROM responders WHERE id=?", (int(request.match_info["id"]),))
        go("/commands", "Deleted.")

    # ---------------- trolls
    @routes.get("/trolls")
    async def trolls_get(request):
        b = bot()
        targets = db.targets()
        for t in targets:
            m = b.get_cog("Trolls").find_member(t["user_id"]) if b else None
            t["name"] = m.display_name if m else (t["label"] or str(t["user_id"]))
            t["in_voice"] = bool(m and m.voice)
        members = []
        if b:
            seen = set()
            for g in b.guilds:
                for m in g.members:
                    if not m.bot and m.id not in seen:
                        seen.add(m.id)
                        members.append((str(m.id), f"{m.display_name} ({m})"))
            members.sort(key=lambda x: x[1].lower())
        return render("trolls.html", request, targets=targets, members=members, types=TROLL_TYPES,
                      descriptions=TROLL_DESCRIPTIONS, actions=ACTIONS, enabled=db.get("trolls_enabled"),
                      chaos=db.get("chaos"), loop=db.get("troll_loop_minutes"), channels=channels())

    @routes.post("/trolls/config")
    async def trolls_config(request):
        f = await request.post()
        db.set("trolls_enabled", "enabled" in f)
        db.set("chaos", max(0.0, min(5.0, float(f.get("chaos") or 1))))
        db.set("troll_loop_minutes", max(1, int(f.get("loop") or 15)))
        go("/trolls", "Chaos parameters updated. 😈")

    @routes.post("/trolls/target")
    async def trolls_target(request):
        f = await request.post()
        uid = (f.get("user_id") or f.get("user_id_manual") or "").strip()
        if not uid.isdigit():
            go("/trolls", "Pick a member or enter a numeric user ID.")
        trolls = [t for t in TROLL_TYPES if f"t_{t}" in f]
        chance_pct = max(0.0, min(100.0, float(f.get("chance") or 15)))
        b = bot()
        m = b.get_cog("Trolls").find_member(uid) if b else None
        db.upsert_target(uid, label=str(m) if m else uid, trolls=trolls, chance=chance_pct / 100)
        go("/trolls", "Target locked in. 🎯")

    @routes.post("/trolls/{uid}/delete")
    async def trolls_delete(request):
        uid = request.match_info["uid"]
        b = bot()
        if b:
            m = b.get_cog("Trolls").find_member(uid)
            if m:
                await b.get_cog("Trolls").run_action("restore_nick", m)
        db.q("DELETE FROM targets WHERE user_id=?", (int(uid),))
        go("/trolls", "Target released. They'll never know.")

    @routes.post("/trolls/{uid}/action")
    async def trolls_action(request):
        f = await request.post()
        b = bot()
        if not b:
            go("/trolls", "Bot is offline.")
        cog = b.get_cog("Trolls")
        m = cog.find_member(request.match_info["uid"])
        if not m:
            go("/trolls", "Member not found in any server.")
        action = f.get("action", "")
        if action not in ACTIONS:
            go("/trolls", "Unknown action.")
        ch = b.get_channel(int(f["channel"])) if f.get("channel", "").isdigit() else None
        if action in ("fake_ban", "voice_shuffle", "voice_mute", "ping_spree", "sound_ambush", "noise_blast",
                      "voice_deafen", "voice_stutter", "voice_jail", "fake_callout", "potato_mode"):
            b.loop.create_task(cog.run_action(action, m, ch))  # these take a while, run in background
            go("/trolls", f"{ACTIONS[action]} launched at {m.display_name}. 🚀")
        result = await cog.run_action(action, m, ch)
        go("/trolls", f"{ACTIONS[action]} → {m.display_name}: {result}")

    # ---------------- say
    @routes.get("/say")
    async def say_get(request):
        return render("say.html", request, channels=channels())

    @routes.post("/say")
    async def say_post(request):
        f = await request.post()
        b = bot()
        ch = b.get_channel(int(f.get("channel", "0"))) if b and f.get("channel", "").isdigit() else None
        if not ch or not f.get("content", "").strip():
            go("/say", "Pick a channel and type something.")
        await ch.send(f["content"][:2000], allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
        db.log("say", f"Panel sent message to #{ch}")
        go("/say", f"Sent to #{ch.name}. They think I'm sentient now.")

    # ---------------- warnings & logs
    @routes.get("/warnings")
    async def warnings_redirect(request):
        go("/cases")

    @routes.get("/cases")
    async def cases_get(request):
        action, user = request.query.get("action", ""), request.query.get("user", "").strip()
        sql, args = "SELECT * FROM cases WHERE 1=1", []
        if action:
            sql += " AND action=?"
            args.append(action)
        if user:
            sql += " AND (CAST(user_id AS TEXT)=? OR user_name LIKE ?)"
            args += [user, f"%{user}%"]
        rows = db.q(sql + " ORDER BY id DESC LIMIT 300", args)
        actions = [r["action"] for r in db.q("SELECT DISTINCT action FROM cases ORDER BY action")]
        quarantined = db.q("SELECT * FROM quarantined ORDER BY ts DESC")
        tempbans = db.q("SELECT * FROM tempbans ORDER BY until")
        return render("cases.html", request, rows=rows, actions=actions, action=action, user=user,
                      quarantined=quarantined, tempbans=tempbans)

    @routes.post("/cases/{id}/delete")
    async def cases_delete(request):
        db.q("DELETE FROM cases WHERE id=?", (int(request.match_info["id"]),))
        go("/cases", "Case removed.")

    @routes.post("/quarantine/{gid}/{uid}/release")
    async def release(request):
        b = bot()
        g = b.get_guild(int(request.match_info["gid"])) if b else None
        m = g.get_member(int(request.match_info["uid"])) if g else None
        if not m:
            db.q("DELETE FROM quarantined WHERE guild_id=? AND user_id=?", (request.match_info["gid"], request.match_info["uid"]))
            go("/cases", "Member not in server any more; record cleared.")
        try:
            await b.get_cog("Security").unquarantine(m, "admin panel")
        except discord.HTTPException as e:
            go("/cases", f"Discord refused: {e.status}")
        go("/cases", f"{m} released from quarantine.")

    # ---------------- server protection controls
    @routes.post("/guild/{gid}/{what}/{state}")
    async def guild_control(request):
        b = bot()
        g = b.get_guild(int(request.match_info["gid"])) if b else None
        if not g:
            go("/", "Bot offline or server not found.")
        sec, on = b.get_cog("Security"), request.match_info["state"] == "on"
        if request.match_info["what"] == "lockdown":
            n = await sec.lockdown(g, on)
            go("/", f"{'Locked' if on else 'Unlocked'} {n} channel(s) in {g.name}.")
        if request.match_info["what"] == "raid":
            await sec.set_raid(g, on, "admin panel")
            go("/", f"Raid mode {'ON' if on else 'off'} for {g.name}.")
        raise web.HTTPNotFound()

    # ---------------- soundboard
    @routes.get("/sounds")
    async def sounds_get(request):
        b = bot()
        vchans, members = [], []
        if b:
            vchans = [(str(c.id), f"{g.name} / 🔊 {c.name} ({len(c.members)})") for g in b.guilds for c in g.voice_channels]
            members = [(str(m.id), f"{m.display_name} in 🔊 {m.voice.channel.name}") for g in b.guilds
                       for m in g.members if m.voice and m.voice.channel and not m.bot]
        clones = db.q("SELECT * FROM voice_clones ORDER BY user_name")
        if b:
            b.get_cog("VoiceClone").expire_pending()
        pending = db.q("SELECT * FROM pending_clones ORDER BY ts DESC")
        all_members = sorted({(str(m.id), f"{m.display_name} ({m})") for g in (b.guilds if b else []) for m in g.members
                              if not m.bot}, key=lambda x: x[1].lower())
        return render("sounds.html", request, sounds=sound_lib.list_sounds(data_dir), vchans=vchans, members=members,
                      clones=clones, clone_url=clone_endpoint()[0], pending=pending, all_members=all_members,
                      volume=db.get("sound_volume"), max_seconds=db.get("sound_max_seconds"))

    @routes.get("/sounds/file/{name}")
    async def sounds_file(request):
        s = sound_lib.find_sound(data_dir, request.match_info["name"])
        if not s:
            raise web.HTTPNotFound()
        return web.FileResponse(s["file"])

    @routes.post("/sounds/config")
    async def sounds_config(request):
        f = await request.post()
        db.set("sound_volume", max(0, min(1000, int(f.get("volume") or 100))))
        db.set("sound_max_seconds", max(1, min(120, int(f.get("max_seconds") or 20))))
        go("/sounds", "Saved. Your friends' eardrums have been notified.")

    @routes.post("/sounds/play")
    async def sounds_play(request):
        f = await request.post()
        b = bot()
        if not b:
            go("/sounds", "Bot offline.")
        board = b.get_cog("Soundboard")
        sound = board.pick(f.get("sound", "loud"))
        times = int(f.get("times") or 1)
        target = f.get("target", "")
        channel = None
        if target.startswith("m:"):
            for g in b.guilds:
                m = g.get_member(int(target[2:]))
                if m and m.voice:
                    channel = m.voice.channel
                    b.stealth[m.id] = time.time() + 30
        elif target.startswith("c:"):
            channel = b.get_channel(int(target[2:]))
        if not channel or not sound:
            go("/sounds", "Pick a sound and a voice channel/member that's in voice.")
        b.loop.create_task(board.play(channel, sound, times))
        go("/sounds", f"🔊 Playing {sound['name']} ×{times} in {channel.name}.")

    @routes.post("/sounds/speak")
    async def sounds_speak(request):
        f = await request.post()
        b = bot()
        text = (f.get("text") or "").strip()
        target = f.get("target", "")
        channel = None
        if b and target.startswith("m:"):
            for g in b.guilds:
                m = g.get_member(int(target[2:]))
                if m and m.voice:
                    channel = m.voice.channel
                    b.stealth[m.id] = time.time() + 30
        elif b and target.startswith("c:"):
            channel = b.get_channel(int(target[2:]))
        if not channel or not text:
            go("/sounds", "Type something and pick a voice channel/member that's in voice.")
        board, voice = b.get_cog("Soundboard"), f.get("voice", "robot")
        if voice.startswith("clone:"):
            b.loop.create_task(board.clone_speak(channel, int(voice[6:]), text[:300]))
            go("/sounds", f"🗣️ Generating the clone voice for {channel.name} (can take a while on CPU). Check Logs if nothing plays.")
        victim = int(target[2:]) if voice == "victim" and target.startswith("m:") else None
        b.loop.create_task(board.speak(channel, text[:300], user_id=victim))
        go("/sounds", f"🗣️ Saying it in {channel.name}.")

    @routes.post("/clones/{uid}/delete")
    async def clones_delete(request):
        b = bot()
        if b:
            b.get_cog("VoiceClone").delete(int(request.match_info["uid"]))
        else:
            db.q("DELETE FROM pending_clones WHERE user_id=?", (int(request.match_info["uid"]),))
            row = db.q("SELECT * FROM voice_clones WHERE user_id=?", (int(request.match_info["uid"]),), one=True)
            if row and row["sample"] and os.path.exists(row["sample"]):
                os.remove(row["sample"])
            db.q("DELETE FROM voice_clones WHERE user_id=?", (int(request.match_info["uid"]),))
        go("/sounds", "Voice clone deleted.")

    @routes.post("/clones/upload")
    async def clones_upload(request):
        b = bot()
        if not b:
            go("/sounds", "The bot must be online to ask your friend for approval.")
        reader = await request.multipart()
        uid, tmp_path = None, None
        try:
            async for part in reader:
                if part.name == "member":
                    uid = (await part.text()).strip()
                elif part.name == "file" and part.filename:
                    ext = os.path.splitext(part.filename)[1].lower() or ".ogg"
                    if ext not in sound_lib.AUDIO_EXT:
                        go("/sounds", "Unsupported file type.")
                    tmp_path = os.path.join(data_dir, f"upload_{os.getpid()}_{time.time_ns()}{ext}")
                    size = 0
                    with open(tmp_path, "wb") as fh:
                        while chunk := await part.read_chunk():
                            size += len(chunk)
                            if size > 10 * 1024 * 1024:
                                go("/sounds", "File too big (max 10 MB).")
                            fh.write(chunk)
            member = b.get_cog("Trolls").find_member(uid) if uid and uid.isdigit() else None
            if not member or not tmp_path:
                go("/sounds", "Pick a member and an audio file.")
            msg = await b.get_cog("VoiceClone").submit_for_approval(member, tmp_path, "admin panel")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        go("/sounds", msg)

    @routes.post("/clones/{uid}/resend")
    async def clones_resend(request):
        b = bot()
        m = b.get_cog("Trolls").find_member(request.match_info["uid"]) if b else None
        if not m:
            go("/sounds", "Bot offline or member not found.")
        go("/sounds", await b.get_cog("VoiceClone").send_request(m))

    @routes.post("/clones/{uid}/cancel")
    async def clones_cancel(request):
        uid = int(request.match_info["uid"])
        row = db.q("SELECT * FROM pending_clones WHERE user_id=?", (uid,), one=True)
        if row and row["sample"] and os.path.exists(row["sample"]):
            os.remove(row["sample"])
        db.q("DELETE FROM pending_clones WHERE user_id=?", (uid,))
        go("/sounds", "Request cancelled and sample deleted.")

    def clone_endpoint():
        url = (db.get("clone_api_url") or "").strip()
        if url:
            return url.rstrip("/"), "admin panel setting"
        env_url = os.environ.get("CLONE_API_URL", "").strip()
        return (env_url.rstrip("/"), "YunoHost plugin") if env_url else ("", "")

    @routes.get("/plugins")
    async def plugins_get(request):
        url, source = clone_endpoint()
        return render("plugins.html", request, clone_url=url, clone_source=source,
                      app_id=os.environ.get("APP_ID", "siegebot"))

    @routes.post("/clones/test")
    async def clones_test(request):
        import aiohttp
        url, _src = clone_endpoint()
        back = request.query.get("back", "/sounds")
        if not url:
            go("/plugins", "No clone service yet. Install the plugin (see below) or set a URL.")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
                async with http.get(url + "/health") as r:
                    msg = f"Clone service OK: {await r.text()}" if r.status == 200 else f"Clone service answered {r.status}"
        except Exception as e:
            msg = f"Can't reach clone service: {e or type(e).__name__}"
        go(back if back in ("/sounds", "/plugins") else "/sounds", msg)

    @routes.post("/sounds/stop")
    async def sounds_stop(request):
        b = bot()
        for g in (b.guilds if b else []):
            await b.get_cog("Soundboard").stop(g)
        go("/sounds", "Silence restored.")

    @routes.post("/sounds/upload")
    async def sounds_upload(request):
        reader = await request.multipart()
        name, saved = None, None
        async for part in reader:
            if part.name == "name":
                name = (await part.text()).strip().lower()
            elif part.name == "file" and part.filename:
                ext = os.path.splitext(part.filename)[1].lower()
                if ext not in sound_lib.AUDIO_EXT:
                    go("/sounds", "Unsupported file type.")
                name = re.sub(r"[^a-z0-9_-]", "_", name or os.path.splitext(part.filename)[0].lower())[:40]
                if not name or name in sound_lib.BUILTIN:
                    go("/sounds", "Pick a different name (built-in sounds can't be overwritten).")
                path = os.path.join(sound_lib.sound_dir(data_dir), name + ext)
                size = 0
                with open(path, "wb") as fh:
                    while chunk := await part.read_chunk():
                        size += len(chunk)
                        if size > 8 * 1024 * 1024:
                            fh.close()
                            os.remove(path)
                            go("/sounds", "File too big (max 8 MB).")
                        fh.write(chunk)
                saved = name
        go("/sounds", f"Uploaded '{saved}'." if saved else "No file received.")

    @routes.post("/sounds/{name}/delete")
    async def sounds_delete(request):
        s = sound_lib.find_sound(data_dir, request.match_info["name"])
        if s and not s["builtin"]:
            os.remove(s["file"])
        go("/sounds", "Deleted." if s and not s["builtin"] else "Built-in sounds can't be deleted.")

    # ---------------- leaderboard
    def lb():
        b = bot()
        return b, (b.get_cog("Leaderboard") if b else None)

    def tier_name(n):
        names = db.get("tier_names") or []
        return f"Tier {n}" + (f": {names[n - 1]}" if 0 < n <= len(names) else "")

    def boards():
        b = bot()
        gids = {g.id: g.name for g in b.guilds} if b else {}
        for r in db.q("SELECT DISTINCT guild_id FROM ratings"):
            gids.setdefault(r["guild_id"], str(r["guild_id"]))
        out = []
        for gid, gname in gids.items():
            rows = db.q("SELECT * FROM ratings WHERE guild_id=? ORDER BY tier, user_name COLLATE NOCASE", (gid,))
            g = b.get_guild(gid) if b else None
            for r in rows:
                m = g.get_member(r["user_id"]) if g else None
                r["display"] = m.display_name if m else r["user_name"].split("#")[0]
                r["avatar"] = m.display_avatar.url if m else None
            out.append({"id": gid, "name": gname, "tiers": [(t, tier_name(t), [r for r in rows if r["tier"] == t]) for t in range(1, 6)],
                        "members": sorted(((str(m.id), f"{m.display_name} ({m})") for m in g.members if not m.bot),
                                          key=lambda x: x[1].lower()) if g else []})
        return out

    @routes.get("/leaderboard")
    async def leaderboard_get(request):
        pending = db.q("SELECT * FROM tier_requests WHERE status='pending' ORDER BY ts")
        history = db.q("SELECT * FROM tier_requests WHERE status!='pending' ORDER BY COALESCE(review_ts, ts) DESC LIMIT 100")
        return render("leaderboard.html", request, boards=boards(), pending=pending, history=history, tier_name=tier_name)

    @routes.post("/leaderboard/set")
    async def leaderboard_set(request):
        f = await request.post()
        b, cog = lb()
        if not cog:
            go("/leaderboard", "Bot offline.")
        g = b.get_guild(int(f.get("guild", "0") or 0))
        uid = f.get("user_id", "")
        m = g.get_member(int(uid)) if g and uid.isdigit() else None
        if not m:
            go("/leaderboard", "Pick a member.")
        tier = max(0, min(5, int(f.get("tier") or 0)))
        cog.set_direct(g.id, m.id, str(m), tier, "admin panel", f.get("reason", "").strip())
        go("/leaderboard", f"{m.display_name} is now {tier_name(tier) if tier else 'unranked'}.")

    @routes.post("/leaderboard/review/{rid}")
    async def leaderboard_review(request):
        f = await request.post()
        b, cog = lb()
        if not cog:
            go("/leaderboard", "Bot offline.")
        msg = await cog.review(int(request.match_info["rid"]), f.get("action") == "approve", "admin panel", f.get("note", ""))
        go("/leaderboard", msg)

    @routes.get("/public/leaderboard")
    async def public_leaderboard(request):
        if not db.get("public_leaderboard"):
            raise web.HTTPNotFound(text="The public leaderboard is turned off.")
        html = env.get_template("public_leaderboard.html").render(boards=boards(), base=base)
        return web.Response(text=html, content_type="text/html")

    @routes.get("/docs")
    async def docs_get(request):
        from .docs import build
        return render("docs.html", request, d=build(), sections_docs=SECTIONS, prefix=db.get("prefix"))

    @routes.get("/logs")
    async def logs_get(request):
        kind = request.query.get("kind")
        rows = (db.q("SELECT * FROM logs WHERE kind=? ORDER BY id DESC LIMIT 300", (kind,)) if kind
                else db.q("SELECT * FROM logs ORDER BY id DESC LIMIT 300"))
        return render("logs.html", request, rows=rows, kind=kind)

    app = web.Application(middlewares=[csrf], client_max_size=10 * 1024 * 1024)
    app.add_routes(routes)
    return app
