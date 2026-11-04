"""Builds the in-panel documentation from the code itself, so it never goes stale."""
from discord import app_commands

from . import sounds
from .defaults import TROLL_DESCRIPTIONS, TROLL_TYPES
from .trolls import ACTIONS, HIDDEN, PASSIVE, VOICE_ACTIONS

PERM_NAMES = {"moderate_members": "Timeout Members", "manage_messages": "Manage Messages", "kick_members": "Kick Members",
              "ban_members": "Ban Members", "manage_channels": "Manage Channels", "manage_nicknames": "Manage Nicknames",
              "administrator": "Administrator"}

HIDDEN_EXTRA = [
    (",,sound @user <name> [times]", "Play a soundboard sound in their call N times (max 10). Without @user it plays in your call. "
                                      "Name can be 'loud' or 'cue' for a random one."),
    (",,tts @user <text>", "Robot voice says anything in their call."),
    (",,clone @user <text>", "That person's opted-in voice clone says something in your call (or theirs if you're not in voice)."),
    (",,stop", "Stop any sound and make the bot leave voice."),
    (",,sounds", "DMs you the list of sound names."),
    (",,target @user", "Add them as a target with every troll enabled."),
    (",,untarget @user", "Release them (restores their nickname)."),
    (",,chaos <0-5>", "Set the chaos multiplier."),
    (",,on / ,,off", "Turn the troll engine on or off."),
    (",,panic", "Emergency: turn everything off and undo nicknames, shame roles, timeouts and potato channels."),
    (",,help", "DMs you the full secret command list."),
]


def _cmd_rows(cog_cls, category):
    rows = []
    for c in cog_cls.__cog_app_commands__:
        subs = c.commands if isinstance(c, app_commands.Group) else [c]
        for s in subs:
            name = f"/{c.name} {s.name}" if isinstance(c, app_commands.Group) else f"/{s.name}"
            params = " ".join(f"<{p.name}>" if p.required else f"[{p.name}]" for p in s.parameters)
            perms = c.default_permissions or getattr(s, "default_permissions", None)
            needed = [PERM_NAMES.get(k, k) for k, v in perms if v] if perms else []
            rows.append({"name": name, "params": params, "desc": s.description, "perms": ", ".join(needed) or "Everyone",
                         "category": category})
    return rows


def build():
    from .fun import Fun
    from .leaderboard import Leaderboard
    from .moderation import Moderation
    from .security import Security
    from .voiceclone import VoiceClone
    commands = (_cmd_rows(Moderation, "Moderation") + _cmd_rows(Security, "Security") + _cmd_rows(Fun, "Fun")
                + _cmd_rows(Leaderboard, "Leaderboard") + _cmd_rows(VoiceClone, "Voice clones"))
    trolls = []
    for t in TROLL_TYPES:
        if t in PASSIVE:
            kind = "Reacts to their messages"
        elif t in ("nick_lock", "typing_sniper", "join_announcer"):
            kind = "Reacts to what they do"
        elif t in ("fake_stats", "cursed_ops"):
            kind = "Rigs commands"
        else:
            kind = "Timed loop / manual"
        trolls.append({"key": t, "desc": TROLL_DESCRIPTIONS.get(t, ""), "kind": kind, "voice": t in VOICE_ACTIONS
                       or t == "read_aloud"})
    hidden = [(f",,{k} @user", f"{ACTIONS.get(v, v)}: {TROLL_DESCRIPTIONS.get(v, '')}".rstrip(": ")) for k, v in HIDDEN.items()]
    hidden += HIDDEN_EXTRA
    return {"commands": commands, "trolls": trolls, "hidden": hidden, "builtin_sounds": sounds.BUILTIN}
