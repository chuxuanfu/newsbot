from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import Candidate, utc_now_iso
from app.scoring import token_similarity


def cluster_candidate(
    conn: sqlite3.Connection,
    candidate: Candidate,
    raw_row: dict[str, Any],
    config: dict[str, Any],
) -> int | None:
    threshold = config.get("scoring", {}).get("digest_priority_threshold", 4.5)
    if not candidate.is_event or candidate.final_priority < threshold:
        return None

    event_id = find_matching_event(conn, candidate, config)
    if event_id:
        update_event(conn, event_id, candidate)
    else:
        event_id = create_event(conn, candidate, raw_row)

    conn.execute(
        """
        INSERT OR IGNORE INTO event_sources(event_id, raw_item_id, created_at)
        VALUES (?, ?, ?)
        """,
        (event_id, candidate.raw_item_id, utc_now_iso()),
    )
    source_count = conn.execute(
        "SELECT COUNT(*) AS c FROM event_sources WHERE event_id = ?",
        (event_id,),
    ).fetchone()["c"]
    conn.execute(
        "UPDATE events SET source_count = ?, updated_at = ? WHERE id = ?",
        (source_count, utc_now_iso(), event_id),
    )
    return event_id


def find_matching_event(
    conn: sqlite3.Connection,
    candidate: Candidate,
    config: dict[str, Any],
) -> int | None:
    hours = int(config.get("runtime", {}).get("cluster_window_hours", 6))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(
        microsecond=0
    ).isoformat()
    rows = list(conn.execute(
        """
        SELECT *
        FROM events
        WHERE status = 'open'
          AND category = ?
          AND last_seen_at >= ?
        ORDER BY last_seen_at DESC
        LIMIT 100
        """,
        (candidate.category, since),
    ))
    cand_locations = {loc.lower() for loc in candidate.locations}
    for row in rows:
        event_locations = {
            loc.strip().lower()
            for loc in (row["location_key"] or "").split(",")
            if loc.strip()
        }
        has_location_overlap = bool(cand_locations and event_locations and cand_locations & event_locations)
        sim = token_similarity(candidate.summary, f"{row['title']} {row['summary']}")
        if has_location_overlap and sim >= 0.08:
            return int(row["id"])
        if not cand_locations and sim >= 0.28:
            return int(row["id"])
        if has_location_overlap and sim >= 0.18:
            return int(row["id"])
    return None


def create_event(conn: sqlite3.Connection, candidate: Candidate, raw_row: dict[str, Any]) -> int:
    now = utc_now_iso()
    title = build_event_title(candidate, raw_row)
    location_key = ",".join(candidate.locations)
    cur = conn.execute(
        """
        INSERT INTO events (
          title, category, location_key, summary, why_it_matters, action_needed,
          first_seen_at, last_seen_at, urgency_score, relevance_score,
          credibility_score, noise_score, final_priority, source_count, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            title,
            candidate.category,
            location_key,
            candidate.summary,
            candidate.why_it_matters,
            candidate.action_needed,
            now,
            now,
            candidate.urgency_score,
            candidate.relevance_score,
            candidate.credibility_score,
            candidate.noise_score,
            candidate.final_priority,
            now,
        ),
    )
    return int(cur.lastrowid)


def update_event(conn: sqlite3.Connection, event_id: int, candidate: Candidate) -> None:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    locations = set(json_like_split(row["location_key"]))
    locations.update(candidate.locations)
    conn.execute(
        """
        UPDATE events
        SET location_key = ?,
            summary = ?,
            why_it_matters = ?,
            action_needed = ?,
            last_seen_at = ?,
            urgency_score = MAX(urgency_score, ?),
            relevance_score = MAX(relevance_score, ?),
            credibility_score = MAX(credibility_score, ?),
            noise_score = MIN(noise_score, ?),
            final_priority = MAX(final_priority, ?),
            updated_at = ?
        WHERE id = ?
        """,
        (
            ",".join(sorted(locations)),
            candidate.summary or row["summary"],
            candidate.why_it_matters or row["why_it_matters"],
            candidate.action_needed or row["action_needed"],
            utc_now_iso(),
            candidate.urgency_score,
            candidate.relevance_score,
            candidate.credibility_score,
            candidate.noise_score,
            candidate.final_priority,
            utc_now_iso(),
            event_id,
        ),
    )


def json_like_split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def build_event_title(candidate: Candidate, raw_row: dict[str, Any]) -> str:
    if candidate.locations:
        prefix = " / ".join(candidate.locations[:2])
        return f"{prefix}: {candidate.summary[:120]}"
    return candidate.summary[:140] or raw_row.get("title", "Untitled event")[:140]
