from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.models import Candidate, RawItem, utc_now_iso


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS raw_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_url TEXT NOT NULL,
  item_url TEXT,
  title TEXT NOT NULL,
  content TEXT,
  author TEXT,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  raw_json TEXT,
  category_hint TEXT,
  content_hash TEXT NOT NULL UNIQUE,
  processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_processed ON raw_items(processed_at, fetched_at);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_items(source_name, published_at);

CREATE TABLE IF NOT EXISTS event_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_item_id INTEGER NOT NULL UNIQUE,
  is_event INTEGER NOT NULL,
  category TEXT,
  locations_json TEXT,
  entities_json TEXT,
  urgency_score REAL,
  relevance_score REAL,
  credibility_score REAL,
  noise_score REAL,
  summary TEXT,
  why_it_matters TEXT,
  action_needed TEXT,
  confidence_reason TEXT,
  final_priority REAL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(raw_item_id) REFERENCES raw_items(id)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  location_key TEXT,
  summary TEXT,
  why_it_matters TEXT,
  action_needed TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  urgency_score REAL,
  relevance_score REAL,
  credibility_score REAL,
  noise_score REAL,
  final_priority REAL,
  source_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open',
  notified_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_open ON events(status, category, last_seen_at);

CREATE TABLE IF NOT EXISTS event_sources (
  event_id INTEGER NOT NULL,
  raw_item_id INTEGER NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  PRIMARY KEY(event_id, raw_item_id),
  FOREIGN KEY(event_id) REFERENCES events(id),
  FOREIGN KEY(raw_item_id) REFERENCES raw_items(id)
);

CREATE TABLE IF NOT EXISTS notification_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER,
  kind TEXT NOT NULL,
  message_hash TEXT NOT NULL UNIQUE,
  sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_item_notifications (
  raw_item_id INTEGER PRIMARY KEY,
  sent_at TEXT NOT NULL,
  FOREIGN KEY(raw_item_id) REFERENCES raw_items(id)
);

CREATE TABLE IF NOT EXISTS source_state (
  source_name TEXT PRIMARY KEY,
  last_run_at TEXT,
  last_status TEXT,
  last_error TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def content_hash(item: RawItem) -> str:
    key = "|".join([
        item.source_name,
        item.item_url or "",
        item.title.strip(),
        item.published_at or "",
        item.content[:500].strip(),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def insert_raw_item(conn: sqlite3.Connection, item: RawItem) -> int | None:
    try:
        cur = conn.execute(
            """
            INSERT INTO raw_items (
              source_name, source_type, source_url, item_url, title, content,
              author, published_at, fetched_at, raw_json, category_hint,
              content_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.source_name,
                item.source_type,
                item.source_url,
                item.item_url,
                item.title[:1000],
                item.content[:10000],
                item.author,
                item.published_at,
                item.fetched_at,
                json.dumps(item.raw, ensure_ascii=False),
                item.category_hint,
                content_hash(item),
            ),
        )
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def get_unprocessed_raw_items(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT *
        FROM raw_items
        WHERE processed_at IS NULL
        ORDER BY fetched_at ASC
        LIMIT ?
        """,
        (limit,),
    ))


def mark_raw_processed(conn: sqlite3.Connection, raw_item_id: int) -> None:
    conn.execute(
        "UPDATE raw_items SET processed_at = ? WHERE id = ?",
        (utc_now_iso(), raw_item_id),
    )


def insert_candidate(conn: sqlite3.Connection, candidate: Candidate) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO event_candidates (
          raw_item_id, is_event, category, locations_json, entities_json,
          urgency_score, relevance_score, credibility_score, noise_score,
          summary, why_it_matters, action_needed, confidence_reason,
          final_priority, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate.raw_item_id,
            1 if candidate.is_event else 0,
            candidate.category,
            json.dumps(candidate.locations, ensure_ascii=False),
            json.dumps(candidate.entities, ensure_ascii=False),
            candidate.urgency_score,
            candidate.relevance_score,
            candidate.credibility_score,
            candidate.noise_score,
            candidate.summary,
            candidate.why_it_matters,
            candidate.action_needed,
            candidate.confidence_reason,
            candidate.final_priority,
            utc_now_iso(),
        ),
    )


def set_source_state(
    conn: sqlite3.Connection,
    source_name: str,
    status: str,
    error: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO source_state(source_name, last_run_at, last_status, last_error)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
          last_run_at = excluded.last_run_at,
          last_status = excluded.last_status,
          last_error = excluded.last_error
        """,
        (source_name, utc_now_iso(), status, error[:1000]),
    )


def message_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
