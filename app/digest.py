from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.notifier import get_event_links, log_notification, send_telegram


def send_daily_digest(conn: sqlite3.Connection, config: dict[str, Any]) -> bool:
    threshold = float(config.get("scoring", {}).get("digest_priority_threshold", 4.5))
    max_items = int(config.get("runtime", {}).get("max_events_for_digest", 20))
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(
        microsecond=0
    ).isoformat()
    rows = list(conn.execute(
        """
        SELECT *
        FROM events
        WHERE last_seen_at >= ?
          AND final_priority >= ?
        ORDER BY final_priority DESC, last_seen_at DESC
        LIMIT ?
        """,
        (since, threshold, max_items),
    ))
    if not rows:
        text = "[DIGEST][DAILY] No high-signal South Bay events found in the last 24 hours."
    else:
        lines = ["[DIGEST][DAILY] South Bay Event Radar", ""]
        for idx, row in enumerate(rows, start=1):
            lines.append(
                f"{idx}. [{str(row['category']).upper()}] {row['title']}"
            )
            links = get_event_links(conn, int(row["id"]), limit=1)
            lines.append(f"   链接：{links[0] if links else '无可用原始链接'}")
        text = "\n".join(lines)[:3900]
    if send_telegram(config, text):
        log_notification(conn, None, "daily_digest", text)
        return True
    return False
