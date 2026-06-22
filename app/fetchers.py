from __future__ import annotations

import io
import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import feedparser
import openpyxl
from bs4 import BeautifulSoup

from app.http_client import get_bytes, get_json, get_text
from app.models import RawItem


def fetch_source(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    source_type = source["type"]
    if source_type == "rss":
        return fetch_rss(source, user_agent)
    if source_type == "reddit_json":
        return fetch_reddit_json(source, user_agent)
    if source_type == "chp_html":
        return fetch_chp_html(source, user_agent)
    if source_type == "nws_alerts":
        return fetch_nws_alerts(source, user_agent)
    if source_type == "usgs_geojson":
        return fetch_usgs_geojson(source, user_agent)
    if source_type == "calfire_json":
        return fetch_calfire_json(source, user_agent)
    if source_type == "warn_xlsx":
        return fetch_warn_xlsx(source, user_agent)
    if source_type == "html_page":
        return fetch_html_page(source, user_agent)
    raise ValueError(f"Unsupported source type: {source_type}")


def base_item(source: dict[str, Any], title: str, content: str = "") -> RawItem:
    return RawItem(
        source_name=source["name"],
        source_type=source["type"],
        source_url=source["url"],
        title=clean_text(title),
        content=clean_text(content),
        category_hint=source.get("category_hint", ""),
    )


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def epoch_to_iso(value: int | float | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(
        microsecond=0
    ).isoformat()


def fetch_rss(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    text = get_text(source["url"], user_agent)
    feed = feedparser.parse(text)
    items: list[RawItem] = []
    for entry in feed.entries:
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        item = base_item(source, title, BeautifulSoup(summary, "html.parser").get_text(" "))
        item.item_url = entry.get("link", "")
        item.author = entry.get("author", "")
        item.published_at = entry.get("published", "") or entry.get("updated", "")
        item.raw = dict(entry)
        items.append(item)
    return items


def fetch_reddit_json(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    try:
        data = get_json(source["url"], user_agent)
    except Exception:
        rss_source = dict(source)
        rss_source["type"] = "rss"
        rss_source["url"] = reddit_json_url_to_rss(source["url"])
        return fetch_rss(rss_source, user_agent)
    items: list[RawItem] = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")
        content = post.get("selftext", "") or post.get("url", "")
        item = base_item(source, title, content)
        permalink = post.get("permalink", "")
        item.item_url = urljoin("https://www.reddit.com", permalink)
        item.author = post.get("author", "")
        item.published_at = epoch_to_iso(post.get("created_utc"))
        item.raw = post
        items.append(item)
    return items


def reddit_json_url_to_rss(url: str) -> str:
    url = re.sub(r"\.json.*$", "/.rss", url)
    if "/new/" not in url and "/new." not in url:
        url = url.rstrip("/") + "/new/.rss"
    return url


def fetch_chp_html(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    html = get_text(source["url"], user_agent)
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    items: list[RawItem] = []
    for row in rows:
        cells = [clean_text(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
        joined = " | ".join(cell for cell in cells if cell)
        if len(joined) < 20:
            continue
        if "time" in joined.lower() and "location" in joined.lower():
            continue
        item = base_item(source, f"CHP Bay Area incident: {cells[0]}", joined)
        item.item_url = source["url"]
        item.raw = {"cells": cells}
        items.append(item)
    if items:
        return items

    text = clean_text(soup.get_text(" "))
    chunks = re.split(r"(?=\d{1,2}:\d{2}\s*[AP]M|\d{2}:\d{2})", text)
    for chunk in chunks:
        if any(word in chunk.lower() for word in ["incident", "traffic", "collision"]):
            item = base_item(source, "CHP Bay Area traffic update", chunk[:1200])
            item.item_url = source["url"]
            items.append(item)
    return items


def fetch_nws_alerts(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    data = get_json(source["url"], user_agent)
    items: list[RawItem] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        title = props.get("headline") or props.get("event") or "NWS alert"
        content = " ".join([
            props.get("description", ""),
            props.get("instruction", ""),
        ])
        item = base_item(source, title, content)
        item.item_url = props.get("@id", "") or props.get("id", "")
        item.published_at = props.get("sent", "") or props.get("effective", "")
        item.raw = props
        items.append(item)
    return items


def fetch_usgs_geojson(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    data = get_json(source["url"], user_agent)
    items: list[RawItem] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if not usgs_relevant(feature, source):
            continue
        title = props.get("title") or "USGS earthquake"
        item = base_item(source, title, props.get("place", ""))
        item.item_url = props.get("url", "")
        item.published_at = epoch_to_iso((props.get("time") or 0) / 1000)
        item.raw = feature
        items.append(item)
    return items


def usgs_relevant(feature: dict[str, Any], source: dict[str, Any]) -> bool:
    center = source.get("center") or {"latitude": 37.3382, "longitude": -121.8863}
    max_km = float(source.get("max_distance_km", 250))
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    props = feature.get("properties") or {}
    mag = float(props.get("mag") or 0)
    min_mag = float(source.get("min_magnitude", 0))
    if len(coords) >= 2:
        distance = haversine_km(float(center["latitude"]), float(center["longitude"]), float(coords[1]), float(coords[0]))
        if distance <= max_km and mag >= min_mag:
            return True
    return mag >= float(source.get("always_include_magnitude", 5.5))


def fetch_calfire_json(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    data = get_json(source["url"], user_agent)
    records = data if isinstance(data, list) else data.get("Incidents", data.get("incidents", []))
    items: list[RawItem] = []
    for rec in records:
        if not calfire_relevant(rec, source):
            continue
        title = rec.get("Name") or rec.get("name") or rec.get("Title") or "CAL FIRE incident"
        content = " ".join(str(rec.get(k, "")) for k in [
            "Location", "County", "AcresBurned", "PercentContained", "Started",
            "Updated", "AdminUnit", "ConditionStatement",
        ])
        item = base_item(source, title, content)
        item.item_url = rec.get("Url", "") or rec.get("url", "") or source["url"]
        item.published_at = rec.get("Started", "") or rec.get("Updated", "")
        item.raw = rec
        items.append(item)
    return items


def calfire_relevant(rec: dict[str, Any], source: dict[str, Any]) -> bool:
    counties = [county.lower() for county in source.get("counties", [])]
    if not counties:
        return True
    text = " ".join(str(rec.get(key, "")) for key in ["County", "Location", "AdminUnit", "Name"]).lower()
    return any(county in text for county in counties)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_warn_xlsx(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    blob = get_bytes(source["url"], user_agent)
    workbook = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    header_idx = 0
    for idx, row in enumerate(rows[:10]):
        lowered = [str(cell or "").lower() for cell in row]
        if any("company" in cell or "employer" in cell for cell in lowered):
            header_idx = idx
            break
    headers = [clean_text(cell) or f"col_{i}" for i, cell in enumerate(rows[header_idx])]
    items: list[RawItem] = []
    for row in rows[header_idx + 1:]:
        values = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        text = " | ".join(f"{k}: {clean_text(v)}" for k, v in values.items() if v)
        if len(text) < 20:
            continue
        company = next(
            (clean_text(v) for k, v in values.items() if "company" in k.lower() or "employer" in k.lower()),
            "",
        )
        title = f"CA WARN notice: {company or text[:80]}"
        item = base_item(source, title, text)
        item.item_url = source["url"]
        item.raw = {k: clean_text(v) for k, v in values.items() if v is not None}
        items.append(item)
    return items


def fetch_html_page(source: dict[str, Any], user_agent: str) -> list[RawItem]:
    html = get_text(source["url"], user_agent)
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title.get_text(" ")) if soup.title else source["name"]
    main = soup.find("main") or soup.body or soup
    content = clean_text(main.get_text(" "))[:9000]
    item = base_item(source, title, content)
    item.item_url = source["url"]
    return [item]
