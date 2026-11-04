"""Admin panel. Sits behind YunoHost SSO (nginx); only listens on 127.0.0.1."""
import os
import time
from datetime import datetime
from urllib.parse import quote, urlparse

import discord
from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .defaults import TROLL_DESCRIPTIONS, TROLL_TYPES
from .trolls import ACTIONS

# section -> (title, intro, [(key, type, label, help)])
SECTIONS = {
    "general": ("General", "Core bot settings.", [
        ("token", "secret", "Bot token", "Leave blank to keep the current one. Saving restarts the bot."),
        ("owner_ids", "str", "Owner Discord IDs", "Comma separated. Owners can use the secret ,, commands and are immune to everything."),
        ("prefix", "str", "Custom command prefix", ""),
        ("status_text", "str", "'Watching ...' status", ""),
        ("welcome_channel_id", "channel", "Welcome channel", ""),
        ("welcome_message", "str", "Welcome message", "Placeholders: {mention} {user} {server}"),
    ]),
    "moderation": ("Moderation", "Automod. Members with Manage Messages, owners and exempt roles are skipped.", [
        ("mod_enabled", "bool", "Automod enabled", ""),
        ("log_channel_id", "channel", "Mod log channel", ""),
        ("banned_words", "lines", "Banned words", "One per line, whole-word match."),
        ("filter_invites", "bool", "Delete Discord invite links", ""),
        ("anti_spam", "bool", "Anti-spam", ""),
        ("spam_messages", "int", "Spam: messages...", ""),
        ("spam_seconds", "float", "...within seconds", ""),
        ("filter_caps", "bool", "Delete ALL CAPS messages", ""),
        ("caps_min_length", "int", "Caps filter minimum letters", ""),
        ("max_warnings", "int", "Warnings before auto-timeout", "0 disables auto-timeout."),
        ("timeout_minutes", "int", "Auto-timeout length (minutes)", ""),
        ("exempt_role_ids", "lines", "Exempt role IDs", "One per line."),
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
    "trollcfg": ("Troll Arsenal", "The content used by the secret trolls.", [
        ("nicknames", "lines", "Humiliating nicknames", "Max 32 characters each."),
        ("reactions", "lines", "Reaction emojis", ""),
        ("cursed_ops", "lines", "Cursed /operator picks", ""),
        ("fake_ban_lines", "lines", "Fake ban announcements", "Use {target}."),
        ("fake_ban_reveal", "lines", "Fake ban 'jk' follow-ups", ""),
        ("dm_reports", "lines", "Fake report DMs", ""),
        ("corrections", "dict", "Autocorrect replacements", "word = replacement, one per line."),
    ]),
}


def create_app(db, ctl, base_path):
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
            "warnings": db.q("SELECT COUNT(*) c FROM warnings", one=True)["c"],
            "targets": db.q("SELECT COUNT(*) c FROM targets", one=True)["c"],
        }
        b = bot()
        uptime = int(time.time() - b.started_at) if b else 0
        return render("dashboard.html", request, stats=stats, uptime=uptime,
                      logs=db.q("SELECT * FROM logs ORDER BY id DESC LIMIT 15"),
                      trolls_enabled=db.get("trolls_enabled"), chaos=db.get("chaos"))

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
                      channels=channels())

    @routes.post("/settings/{section}")
    async def settings_post(request):
        sec = request.match_info["section"]
        if sec not in SECTIONS:
            raise web.HTTPNotFound()
        form = await request.post()
        restart = False
        for key, typ, _label, _help in SECTIONS[sec][2]:
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
            elif typ == "secret":
                if not raw.strip():
                    continue
                val, restart = raw.strip(), True
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
        if action in ("fake_ban", "voice_shuffle", "voice_mute"):
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
    async def warnings_get(request):
        return render("warnings.html", request, rows=db.q("SELECT * FROM warnings ORDER BY ts DESC LIMIT 300"))

    @routes.post("/warnings/{id}/delete")
    async def warnings_delete(request):
        db.q("DELETE FROM warnings WHERE id=?", (int(request.match_info["id"]),))
        go("/warnings", "Warning removed.")

    @routes.get("/logs")
    async def logs_get(request):
        kind = request.query.get("kind")
        rows = (db.q("SELECT * FROM logs WHERE kind=? ORDER BY id DESC LIMIT 300", (kind,)) if kind
                else db.q("SELECT * FROM logs ORDER BY id DESC LIMIT 300"))
        return render("logs.html", request, rows=rows, kind=kind)

    app = web.Application(middlewares=[csrf])
    app.add_routes(routes)
    return app
