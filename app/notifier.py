from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from app.config import env_value
from app.geo import chp_notification_context
from app.models import utc_now_iso
from app.summarizer import should_summarize, summarize_for_notification


def should_notify_event(row: sqlite3.Row, config: dict[str, Any]) -> bool:
    scoring = config.get("scoring", {})
    return (
        float(row["urgency_score"] or 0) >= float(scoring.get("immediate_min_urgency", 8))
        and float(row["relevance_score"] or 0) >= float(scoring.get("immediate_min_relevance", 7))
        and float(row["credibility_score"] or 0) >= float(scoring.get("immediate_min_credibility", 4))
    )


def notify_due_events(conn: sqlite3.Connection, config: dict[str, Any]) -> int:
    rows = list(conn.execute(
        """
        SELECT *
        FROM events
        WHERE status = 'open'
          AND notified_at IS NULL
        ORDER BY final_priority DESC, last_seen_at DESC
        LIMIT 50
        """
    ))
    sent = 0
    for row in rows:
        if not should_notify_event(row, config):
            continue
        if hourly_limit_reached(conn, config):
            break
        message = format_event_message(conn, row, kind="IMMEDIATE")
        if send_telegram(config, message):
            log_notification(conn, int(row["id"]), "immediate", message)
            conn.execute(
                "UPDATE events SET notified_at = ?, updated_at = ? WHERE id = ?",
                (utc_now_iso(), utc_now_iso(), int(row["id"])),
            )
            sent += 1
    return sent


def notify_new_raw_items(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    raw_item_ids: list[int],
) -> int:
    notifications = config.get("notifications", {})
    if not notifications.get("notify_all_new_raw_items", False):
        return 0
    if not raw_item_ids:
        return 0
    max_per_fetch = int(notifications.get("notify_raw_item_max_per_fetch", 30))
    sent = 0
    for raw_item_id in raw_item_ids[:max_per_fetch]:
        row = conn.execute(
            """
            SELECT *
            FROM raw_items
            WHERE id = ?
              AND id NOT IN (SELECT raw_item_id FROM raw_item_notifications)
            """,
            (raw_item_id,),
        ).fetchone()
        if not row:
            continue
        if is_stale_rss_item(row, config):
            continue
        map_path = None
        if row["source_name"] == "chp_bay_area":
            context = chp_notification_context(conn, row, config)
            if not context:
                continue
            map_path = context.get("map_path")
            message = format_raw_item_message(row, config, context=context)
        else:
            message = format_raw_item_message(row, config)
        sent_ok = send_telegram_photo(config, map_path, message) if map_path else send_telegram(config, message)
        if sent_ok:
            conn.execute(
                """
                INSERT OR IGNORE INTO raw_item_notifications(raw_item_id, sent_at)
                VALUES (?, ?)
                """,
                (raw_item_id, utc_now_iso()),
            )
            log_notification(conn, None, "raw_new", message)
            sent += 1
    return sent


def hourly_limit_reached(conn: sqlite3.Connection, config: dict[str, Any]) -> bool:
    limit = int(config.get("notifications", {}).get("max_immediate_per_hour", 8))
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(
        microsecond=0
    ).isoformat()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM notification_log WHERE kind = 'immediate' AND sent_at >= ?",
        (since,),
    ).fetchone()["c"]
    return int(count) >= limit


def format_event_message(conn: sqlite3.Connection, row: sqlite3.Row, kind: str) -> str:
    links = get_event_links(conn, int(row["id"]))
    lines = [
        f"[{kind}][{str(row['category']).upper()}] {row['title']}",
        "",
        f"摘要：{clean_line(row['summary'])}",
    ]
    lines.extend(format_links(links))
    return "\n".join(lines)[:3900]


def get_event_links(conn: sqlite3.Connection, event_id: int, limit: int = 3) -> list[str]:
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(ri.item_url, ''), ri.source_url) AS url
        FROM event_sources es
        JOIN raw_items ri ON ri.id = es.raw_item_id
        WHERE es.event_id = ?
        ORDER BY ri.fetched_at DESC
        LIMIT ?
        """,
        (event_id, limit),
    ).fetchall()
    links: list[str] = []
    for row in rows:
        url = clean_line(row["url"])
        if url and url not in links:
            links.append(url)
    return links


def format_links(links: list[str]) -> list[str]:
    if not links:
        return ["", "链接：无可用原始链接"]
    lines = ["", "链接："]
    lines.extend(links)
    return lines


def format_raw_item_message(
    row: sqlite3.Row,
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> str:
    title = clean_line(row["title"]) or "Untitled"
    source = row["source_name"]
    category = row["category_hint"] or row["source_type"]
    content = clean_line(row["content"] or "")
    item_url = row["item_url"] or row["source_url"]
    summary = summarize_for_notification(row, config) if should_summarize(row) else ""
    lines = [
        f"[NEW][{str(category).upper()}] {title}",
        "",
        f"Source: {source}",
    ]
    if row["published_at"]:
        lines.append(f"Published: {row['published_at']}")
    if context:
        lines.append(f"Map: {context['display_name']} ({context['distance_miles']:.1f} mi from San Jose)")
    if summary:
        lines.extend(["", f"摘要：{summary}"])
    elif content and content != title:
        lines.extend(["", content[:1200]])
    if item_url:
        lines.extend(["", "链接：", item_url])
    else:
        lines.extend(["", "链接：无可用原始链接"])
    return "\n".join(lines)[:3900]


def clean_line(value: str) -> str:
    return " ".join(str(value or "").split())


def is_stale_rss_item(row: sqlite3.Row, config: dict[str, Any]) -> bool:
    if row["source_type"] != "rss" and row["category_hint"] != "local_news":
        return False
    max_age_hours = float(config.get("notifications", {}).get("rss_max_age_hours", 24))
    published_at = parse_datetime(row["published_at"] or "")
    if not published_at:
        return False
    age = datetime.now(timezone.utc) - published_at
    return age > timedelta(hours=max_age_hours)


def parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def send_telegram(config: dict[str, Any], text: str) -> bool:
    notifications = config.get("notifications", {})
    if not notifications.get("telegram_enabled", True):
        return False
    token = env_value(notifications.get("bot_token_env"))
    chat_id = env_value(notifications.get("chat_id_env"))
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        },
        timeout=20,
    )
    response.raise_for_status()
    return True


def send_telegram_photo(config: dict[str, Any], photo_path: str | None, caption: str) -> bool:
    if not photo_path:
        return send_telegram(config, caption)
    notifications = config.get("notifications", {})
    token = env_value(notifications.get("bot_token_env"))
    chat_id = env_value(notifications.get("chat_id_env"))
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    try:
        with open(photo_path, "rb") as photo:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption[:1000],
                },
                files={"photo": photo},
                timeout=30,
            )
        response.raise_for_status()
        return True
    except Exception:
        return send_telegram(config, caption)


def log_notification(conn: sqlite3.Connection, event_id: int | None, kind: str, text: str) -> None:
    digest = hashlib.sha256(f"{kind}:{event_id}:{text}".encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT OR IGNORE INTO notification_log(event_id, kind, message_hash, sent_at)
        VALUES (?, ?, ?, ?)
        """,
        (event_id, kind, digest, utc_now_iso()),
    )
