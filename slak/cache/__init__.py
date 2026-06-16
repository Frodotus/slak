# slak — Terminal Slack client
# Copyright (C) 2026 Toni Leino
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""SQLite cache — a disposable local cache, never the source of truth.

Slack's API is authoritative. This layer enables instant startup, offline
browsing, and (later) FTS search. A corrupt DB is simply deleted and rebuilt.

This MVP slice implements the schema plus the core message and read-state
queries; freshness tiers, FTS, subscriptions, etc. layer on later.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass

log = logging.getLogger("slak.cache")

# Bumped when the FTS index layout changes; gates a one-time rebuild on open.
FTS_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL DEFAULT 'channel',
    topic         TEXT NOT NULL DEFAULT '',
    is_member     INTEGER NOT NULL DEFAULT 1,
    is_muted      INTEGER NOT NULL DEFAULT 0,
    last_read_ts  TEXT NOT NULL DEFAULT '',
    has_unread    INTEGER NOT NULL DEFAULT 0,
    synced_at     INTEGER NOT NULL DEFAULT 0,
    updated_at    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    ts            TEXT NOT NULL,
    channel_id    TEXT NOT NULL,
    workspace_id  TEXT NOT NULL,
    user_id       TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL DEFAULT '',
    thread_ts     TEXT NOT NULL DEFAULT '',
    reply_count   INTEGER NOT NULL DEFAULT 0,
    subtype       TEXT NOT NULL DEFAULT '',
    is_edited     INTEGER NOT NULL DEFAULT 0,
    is_deleted    INTEGER NOT NULL DEFAULT 0,
    raw_json      TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ts, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_ts, channel_id);
"""

# Optional full-text index; skipped gracefully if the sqlite build lacks FTS5.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(text, content='messages', content_rowid='rowid',
               tokenize='unicode61 remove_diacritics 2');

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


@dataclass
class Channel:
    id: str
    workspace_id: str
    name: str
    type: str = "channel"
    topic: str = ""
    is_member: bool = True
    is_muted: bool = False


@dataclass
class Message:
    ts: str
    channel_id: str
    workspace_id: str
    user_id: str = ""
    text: str = ""
    thread_ts: str = ""
    reply_count: int = 0
    subtype: str = ""
    is_edited: bool = False
    is_deleted: bool = False
    raw_json: str = ""
    created_at: int = 0


@dataclass
class ReadState:
    last_read_ts: str
    has_unread: bool


class Cache:
    def __init__(self, conn: sqlite3.Connection, fts: bool):
        self._conn = conn
        self._fts = fts

    @classmethod
    def open(cls, path: str) -> "Cache":
        """Open the cache, rebuilding from scratch if the file is corrupt.

        The cache is disposable (Slack is the source of truth), so a malformed
        DB is discarded and recreated rather than crashing the app.
        """
        try:
            return cls._connect(path)
        except sqlite3.DatabaseError as exc:
            if path == ":memory:":
                raise
            log.warning("cache at %s is unusable (%s); rebuilding", path, exc)
            cls._discard(path)
            return cls._connect(path)

    @classmethod
    def _connect(cls, path: str) -> "Cache":
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        if path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
            row = conn.execute("PRAGMA quick_check").fetchone()
            if row is not None and row[0] != "ok":
                conn.close()
                raise sqlite3.DatabaseError("integrity check failed")
        conn.executescript(SCHEMA)
        fts = cls._setup_fts(conn)
        return cls(conn, fts)

    @classmethod
    def _setup_fts(cls, conn: sqlite3.Connection) -> bool:
        """Create the FTS index, rebuilding it once for caches that predate it.

        A cache created before the FTS index has message rows that were never
        indexed; the sync triggers would then raise "database disk image is
        malformed" on the next write. We gate a one-time ``rebuild`` on
        ``PRAGMA user_version`` so it runs exactly once, recreate the index if it
        is itself corrupt, and fall back to LIKE search if FTS5 is unavailable.
        """
        try:
            conn.executescript(FTS_SCHEMA)
        except sqlite3.OperationalError:
            return False  # sqlite built without FTS5
        if conn.execute("PRAGMA user_version").fetchone()[0] >= FTS_VERSION:
            return True
        try:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        except sqlite3.DatabaseError:
            log.warning("FTS index corrupt; recreating it")
            try:
                conn.executescript("DROP TABLE IF EXISTS messages_fts;")
                conn.executescript(FTS_SCHEMA)
                conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            except sqlite3.DatabaseError:
                return False  # give up on FTS; LIKE fallback keeps search working
        conn.execute(f"PRAGMA user_version = {FTS_VERSION}")
        conn.commit()
        return True

    @staticmethod
    def _discard(path: str) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass

    def close(self) -> None:
        """Checkpoint the WAL and close. Idempotent and never raises."""
        if self._conn is None:
            return
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        try:
            self._conn.close()
        finally:
            self._conn = None

    # --- messages ---------------------------------------------------------

    def add_message(self, m: Message) -> None:
        self._conn.execute(
            """
            INSERT INTO messages
                (ts, channel_id, workspace_id, user_id, text, thread_ts,
                 reply_count, subtype, is_edited, is_deleted, raw_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ts, channel_id) DO UPDATE SET
                user_id=excluded.user_id, text=excluded.text,
                thread_ts=excluded.thread_ts, reply_count=excluded.reply_count,
                subtype=excluded.subtype, is_edited=excluded.is_edited,
                is_deleted=excluded.is_deleted, raw_json=excluded.raw_json
            """,
            (
                m.ts, m.channel_id, m.workspace_id, m.user_id, m.text, m.thread_ts,
                m.reply_count, m.subtype, int(m.is_edited), int(m.is_deleted),
                m.raw_json, m.created_at,
            ),
        )
        self._conn.commit()

    def edit_message(self, channel_id: str, ts: str, text: str) -> None:
        """Update a message's text in place (after an edit)."""
        self._conn.execute(
            "UPDATE messages SET text = ?, is_edited = 1 "
            "WHERE channel_id = ? AND ts = ?",
            (text, channel_id, ts),
        )
        self._conn.commit()

    def delete_message(self, channel_id: str, ts: str) -> None:
        """Soft-delete a message so it stops appearing in ``get_messages``."""
        self._conn.execute(
            "UPDATE messages SET is_deleted = 1 WHERE channel_id = ? AND ts = ?",
            (channel_id, ts),
        )
        self._conn.commit()

    def get_messages(self, channel_id: str, limit: int = 50) -> list[Message]:
        """Return up to ``limit`` newest messages, oldest-first."""
        rows = self._conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE channel_id = ? AND is_deleted = 0
                ORDER BY CAST(ts AS REAL) DESC LIMIT ?
            ) ORDER BY CAST(ts AS REAL) ASC
            """,
            (channel_id, limit),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    @staticmethod
    def _row_to_message(r: sqlite3.Row) -> Message:
        return Message(
            ts=r["ts"], channel_id=r["channel_id"], workspace_id=r["workspace_id"],
            user_id=r["user_id"], text=r["text"], thread_ts=r["thread_ts"],
            reply_count=r["reply_count"], subtype=r["subtype"],
            is_edited=bool(r["is_edited"]), is_deleted=bool(r["is_deleted"]),
            raw_json=r["raw_json"], created_at=r["created_at"],
        )

    def search_messages(self, channel_id: str, query: str, limit: int = 200) -> list[str]:
        """Return ts of messages in ``channel_id`` matching ``query``, newest-first.

        Terms are prefix-matched and AND-ed. Uses FTS5 when available, else LIKE.
        """
        terms = query.split()
        if not terms:
            return []
        if self._fts:
            match = " ".join(f'"{t}"*' for t in terms)
            rows = self._conn.execute(
                """
                SELECT m.ts FROM messages_fts f
                JOIN messages m ON m.rowid = f.rowid
                WHERE f.text MATCH ? AND m.channel_id = ? AND m.is_deleted = 0
                ORDER BY CAST(m.ts AS REAL) DESC LIMIT ?
                """,
                (match, channel_id, limit),
            ).fetchall()
        else:
            clause = " AND ".join("text LIKE ?" for _ in terms)
            params = [f"%{t}%" for t in terms] + [channel_id, limit]
            rows = self._conn.execute(
                f"""
                SELECT ts FROM messages
                WHERE {clause} AND channel_id = ? AND is_deleted = 0
                ORDER BY CAST(ts AS REAL) DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [r["ts"] for r in rows]

    # --- channels & read state -------------------------------------------

    def upsert_channel(self, c: Channel) -> None:
        self._conn.execute(
            """
            INSERT INTO channels (id, workspace_id, name, type, topic, is_member, is_muted)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                workspace_id=excluded.workspace_id, name=excluded.name,
                type=excluded.type, topic=excluded.topic,
                is_member=excluded.is_member, is_muted=excluded.is_muted
            """,
            (c.id, c.workspace_id, c.name, c.type, c.topic, int(c.is_member), int(c.is_muted)),
        )
        self._conn.commit()

    def list_channels(self, workspace_id: str) -> list[Channel]:
        rows = self._conn.execute(
            "SELECT * FROM channels WHERE workspace_id = ?", (workspace_id,)
        ).fetchall()
        return [
            Channel(
                id=r["id"], workspace_id=r["workspace_id"], name=r["name"],
                type=r["type"], topic=r["topic"], is_member=bool(r["is_member"]),
                is_muted=bool(r["is_muted"]),
            )
            for r in rows
        ]

    def update_read_state(self, channel_id: str, last_read_ts: str, has_unread: bool) -> None:
        self._conn.execute(
            "UPDATE channels SET last_read_ts = ?, has_unread = ? WHERE id = ?",
            (last_read_ts, int(has_unread), channel_id),
        )
        self._conn.commit()

    def get_workspace_read_state(self, workspace_id: str) -> dict[str, ReadState]:
        rows = self._conn.execute(
            "SELECT id, last_read_ts, has_unread FROM channels WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        return {
            r["id"]: ReadState(last_read_ts=r["last_read_ts"], has_unread=bool(r["has_unread"]))
            for r in rows
        }

    def workspaces_with_unreads(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT workspace_id FROM channels WHERE has_unread = 1 ORDER BY workspace_id"
        ).fetchall()
        return [r["workspace_id"] for r in rows]
