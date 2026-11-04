"""Tiny SQLite storage: settings (JSON key/value) + a few tables."""
import json
import os
import sqlite3
import threading
import time

from .defaults import DEFAULTS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands (
    name TEXT PRIMARY KEY, response TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, uses INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS responders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL, response TEXT NOT NULL,
    match TEXT NOT NULL DEFAULT 'contains', chance REAL NOT NULL DEFAULT 1.0);
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, user_name TEXT,
    mod_name TEXT, reason TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS targets (
    user_id INTEGER PRIMARY KEY, label TEXT, trolls TEXT NOT NULL DEFAULT '[]',
    chance REAL NOT NULL DEFAULT 0.15, original_nick TEXT, nick_changed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, user_name TEXT, mod_name TEXT,
    action TEXT NOT NULL, reason TEXT, ts REAL, duration INTEGER);
CREATE TABLE IF NOT EXISTS tempbans (guild_id INTEGER, user_id INTEGER, until REAL, PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS quarantined (
    guild_id INTEGER, user_id INTEGER, roles TEXT NOT NULL DEFAULT '[]', ts REAL, PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, message TEXT);
"""


class DB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(_SCHEMA)
            # v1 -> v2: warnings became cases
            if not self.conn.execute("SELECT 1 FROM cases LIMIT 1").fetchone():
                self.conn.execute("""INSERT INTO cases(guild_id,user_id,user_name,mod_name,action,reason,ts)
                                     SELECT guild_id,user_id,user_name,mod_name,'warn',reason,ts FROM warnings""")
                self.conn.execute("DELETE FROM warnings")
            self.conn.commit()

    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall()
            self.conn.commit()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows

    # ---- settings ----
    def get(self, key):
        row = self.q("SELECT value FROM settings WHERE key=?", (key,), one=True)
        if row is None:
            return DEFAULTS.get(key)
        return json.loads(row["value"])

    def set(self, key, value):
        self.q("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))

    def all_settings(self):
        out = dict(DEFAULTS)
        for r in self.q("SELECT key,value FROM settings"):
            out[r["key"]] = json.loads(r["value"])
        return out

    # ---- logs ----
    def log(self, kind, message):
        self.q("INSERT INTO logs(ts,kind,message) VALUES(?,?,?)", (time.time(), kind, str(message)[:1000]))
        self.q("DELETE FROM logs WHERE id < (SELECT MAX(id) FROM logs) - 2000")

    # ---- cases ----
    def add_case(self, guild_id, user, moderator, action, reason, duration=None):
        self.q("INSERT INTO cases(guild_id,user_id,user_name,mod_name,action,reason,ts,duration) VALUES(?,?,?,?,?,?,?,?)",
               (guild_id, user.id, str(user), str(moderator), action, reason, time.time(), duration))
        return self.q("SELECT MAX(id) id FROM cases", one=True)["id"]

    # ---- targets ----
    def targets(self):
        rows = self.q("SELECT * FROM targets")
        for r in rows:
            r["trolls"] = json.loads(r["trolls"])
        return rows

    def target(self, user_id):
        r = self.q("SELECT * FROM targets WHERE user_id=?", (int(user_id),), one=True)
        if r:
            r["trolls"] = json.loads(r["trolls"])
        return r

    def upsert_target(self, user_id, label="", trolls=None, chance=0.15):
        from .defaults import TROLL_TYPES
        trolls = list(TROLL_TYPES) if trolls is None else trolls
        self.q("""INSERT INTO targets(user_id,label,trolls,chance) VALUES(?,?,?,?)
                  ON CONFLICT(user_id) DO UPDATE SET label=excluded.label, trolls=excluded.trolls, chance=excluded.chance""",
               (int(user_id), label, json.dumps(trolls), float(chance)))
