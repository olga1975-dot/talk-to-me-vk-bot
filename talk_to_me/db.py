from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class Profile:
    user_id: int
    name: str = ""
    age: int | None = None
    level: str = ""
    interests: str = ""
    topic: str = ""
    mode: str = "text"
    current_question: str = ""
    bad_answer_count: int = 0
    voice_reply_count: int = 0
    voice_input_count: int = 0
    ai_reply_count: int = 0

    @property
    def complete(self) -> bool:
        return bool(self.name and self.age and self.level and self.interests)


class Database:
    def __init__(self, path: str):
        self.path = path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                    age INTEGER, level TEXT NOT NULL DEFAULT '', interests TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'text',
                    current_question TEXT NOT NULL DEFAULT '', bad_answer_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            columns = {row[1] for row in con.execute("PRAGMA table_info(profiles)")}
            if "voice_reply_count" not in columns:
                con.execute(
                    "ALTER TABLE profiles ADD COLUMN voice_reply_count INTEGER NOT NULL DEFAULT 0"
                )
            if "voice_input_count" not in columns:
                con.execute(
                    "ALTER TABLE profiles ADD COLUMN voice_input_count INTEGER NOT NULL DEFAULT 0"
                )
            if "ai_reply_count" not in columns:
                con.execute(
                    "ALTER TABLE profiles ADD COLUMN ai_reply_count INTEGER NOT NULL DEFAULT 0"
                )

    def get_profile(self, user_id: int) -> Profile:
        with self._connect() as con:
            row = con.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
            if row is None:
                con.execute("INSERT INTO profiles(user_id) VALUES (?)", (user_id,))
                return Profile(user_id=user_id)
            return Profile(**dict(row))

    def save_profile(self, profile: Profile) -> None:
        fields = asdict(profile)
        user_id = fields.pop("user_id")
        columns = list(fields)
        values = [fields[c] for c in columns]
        updates = ", ".join(f"{c}=?" for c in columns)
        with self._connect() as con:
            con.execute(f"UPDATE profiles SET {updates} WHERE user_id=?", values + [user_id])

    def reset(self, user_id: int) -> Profile:
        with self._connect() as con:
            con.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
            con.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
        return self.get_profile(user_id)

    def add_message(self, user_id: int, role: str, content: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO messages(user_id, role, content, created_at) VALUES (?,?,?,?)",
                (user_id, role, content, datetime.now(timezone.utc).isoformat()),
            )

    def history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear_history(self, user_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
