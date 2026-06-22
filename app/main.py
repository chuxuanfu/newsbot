from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.classifier import classify_row
from app.cluster import cluster_candidate
from app.config import load_settings
from app.db import (
    connect,
    get_unprocessed_raw_items,
    init_db,
    insert_candidate,
    insert_raw_item,
    mark_raw_processed,
    set_source_state,
)
from app.digest import send_daily_digest
from app.fetchers import fetch_source
from app.notifier import notify_due_events, send_telegram
from app.notifier import notify_new_raw_items


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("newsbot")


def main() -> None:
    parser = argparse.ArgumentParser(description="South Bay Newsbot")
    parser.add_argument("command", choices=[
        "init-db",
        "fetch",
        "process",
        "notify",
        "digest",
        "backfill-rss",
        "run-once",
        "daemon",
        "test-telegram",
        "status",
    ])
    parser.add_argument("--limit-per-source", type=int, default=2)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    conn = connect(settings.db_path)
    init_db(conn)

    if args.command == "init-db":
        log.info("initialized database at %s", settings.db_path)
    elif args.command == "fetch":
        run_fetch(conn, settings.config, only_due=False)
    elif args.command == "process":
        run_process(conn, settings.config)
    elif args.command == "notify":
        sent = notify_due_events(conn, settings.config)
        conn.commit()
        log.info("sent %s notifications", sent)
    elif args.command == "digest":
        send_daily_digest(conn, settings.config)
        conn.commit()
    elif args.command == "backfill-rss":
        sent = backfill_rss(conn, settings.config, args.limit_per_source)
        conn.commit()
        log.info("backfilled %s RSS/local-news notifications", sent)
    elif args.command == "run-once":
        run_once(conn, settings.config, only_due=False)
    elif args.command == "daemon":
        run_daemon(conn, settings.config)
    elif args.command == "test-telegram":
        send_telegram(settings.config, "[TEST] South Bay Newsbot Telegram is working.")
        log.info("telegram test sent")
    elif args.command == "status":
        print_status(conn)


def run_daemon(conn, config: dict[str, Any]) -> None:
    log.info("starting daemon")
    while True:
        started = time.time()
        try:
            run_once(conn, config, only_due=True)
        except Exception:
            log.exception("daemon iteration failed")
        sleep_for = max(1, int(config.get("runtime", {}).get("poll_sleep_seconds", 10)) - int(time.time() - started))
        time.sleep(sleep_for)


def run_once(conn, config: dict[str, Any], only_due: bool) -> None:
    inserted = run_fetch(conn, config, only_due=only_due)
    processed = run_process(conn, config)
    sent = notify_due_events(conn, config)
    conn.commit()
    log.info("cycle done: inserted=%s processed=%s notified=%s", inserted, processed, sent)


def run_fetch(conn, config: dict[str, Any], only_due: bool) -> int:
    user_agent = config.get("app", {}).get("user_agent", "SouthBayNewsbot/0.1")
    total = 0
    for source in config.get("sources", []):
        if only_due and not source_due(conn, source):
            continue
        try:
            first_run = not source_has_state(conn, source)
            items = fetch_source(source, user_agent)
            inserted = 0
            inserted_ids: list[int] = []
            for item in items:
                raw_item_id = insert_raw_item(conn, item)
                if raw_item_id:
                    inserted += 1
                    inserted_ids.append(raw_item_id)
            total += inserted
            should_notify = (
                not first_run
                or bool(config.get("notifications", {}).get("notify_on_first_fetch", False))
            )
            notified = notify_new_raw_items(conn, config, inserted_ids) if should_notify else 0
            set_source_state(conn, source["name"], f"ok inserted={inserted}")
            conn.commit()
            log.info(
                "fetched %s: %s items, %s new, %s raw notifications",
                source["name"],
                len(items),
                inserted,
                notified,
            )
        except Exception as exc:
            set_source_state(conn, source["name"], "error", str(exc))
            conn.commit()
            log.warning("fetch failed for %s: %s", source["name"], exc)
        finally:
            if source.get("type") == "reddit_json":
                time.sleep(float(config.get("runtime", {}).get("reddit_request_delay_seconds", 8)))
    return total


def source_has_state(conn, source: dict[str, Any]) -> bool:
    row = conn.execute(
        "SELECT 1 FROM source_state WHERE source_name = ?",
        (source["name"],),
    ).fetchone()
    return bool(row)


def source_due(conn, source: dict[str, Any]) -> bool:
    row = conn.execute(
        "SELECT last_run_at FROM source_state WHERE source_name = ?",
        (source["name"],),
    ).fetchone()
    if not row or not row["last_run_at"]:
        return True
    try:
        last = datetime.fromisoformat(row["last_run_at"])
    except ValueError:
        return True
    interval = int(source.get("interval_seconds", 300))
    return (datetime.now(timezone.utc) - last).total_seconds() >= interval


def run_process(conn, config: dict[str, Any]) -> int:
    limit = int(config.get("runtime", {}).get("process_batch_size", 30))
    rows = get_unprocessed_raw_items(conn, limit)
    processed = 0
    for row in rows:
        row_dict = dict(row)
        candidate = classify_row(row_dict, config)
        insert_candidate(conn, candidate)
        cluster_candidate(conn, candidate, row_dict, config)
        mark_raw_processed(conn, int(row["id"]))
        processed += 1
        conn.commit()
        log.info(
            "processed raw_id=%s event=%s category=%s priority=%.1f",
            row["id"],
            candidate.is_event,
            candidate.category,
            candidate.final_priority,
        )
    return processed


def backfill_rss(conn, config: dict[str, Any], limit_per_source: int) -> int:
    source_names = [
        source["name"]
        for source in config.get("sources", [])
        if source.get("type") == "rss" or source.get("category_hint") == "local_news"
    ]
    total = 0
    for source_name in source_names:
        rows = list(conn.execute(
            """
            SELECT id
            FROM raw_items
            WHERE source_name = ?
              AND id NOT IN (SELECT raw_item_id FROM raw_item_notifications)
            ORDER BY
              CASE WHEN published_at IS NULL OR published_at = '' THEN fetched_at ELSE published_at END DESC,
              id DESC
            LIMIT ?
            """,
            (source_name, limit_per_source),
        ))
        raw_item_ids = [int(row["id"]) for row in rows]
        if not raw_item_ids:
            continue
        sent = notify_new_raw_items(conn, config, raw_item_ids)
        conn.commit()
        total += sent
        log.info("backfilled %s: requested=%s sent=%s", source_name, len(raw_item_ids), sent)
    return total


def print_status(conn) -> None:
    payload = {
        "raw_items": conn.execute("SELECT COUNT(*) AS c FROM raw_items").fetchone()["c"],
        "unprocessed": conn.execute("SELECT COUNT(*) AS c FROM raw_items WHERE processed_at IS NULL").fetchone()["c"],
        "events": conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"],
        "notifications": conn.execute("SELECT COUNT(*) AS c FROM notification_log").fetchone()["c"],
        "sources": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM source_state ORDER BY source_name"
            )
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
