from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

import certifi
import requests
from staticmap import CircleMarker, StaticMap

from app.models import utc_now_iso


LOCALITY_HINTS = [
    "San Jose",
    "Santa Clara",
    "Cupertino",
    "Sunnyvale",
    "Milpitas",
    "Campbell",
    "Mountain View",
    "Palo Alto",
    "Los Gatos",
    "Saratoga",
    "Los Altos",
    "Fremont",
    "Newark",
    "Union City",
    "Morgan Hill",
    "Redwood City",
    "Menlo Park",
    "San Mateo",
    "Hayward",
    "Newark",
    "Pleasanton",
]

OUT_OF_AREA_HINTS = [
    "Marin",
    "Napa",
    "Solano",
    "Sonoma",
    "Santa Rosa",
    "San Francisco",
    "Oakland",
    "Contra Costa",
    "Walnut Creek",
    "Lafayette",
    "Orinda",
    "Berkeley",
    "Richmond",
    "Vallejo",
    "Fairfield",
    "Antioch",
]

NEARBY_CITY_FALLBACKS = {
    "San Jose": ["San Jose", "Santa Clara", "Sunnyvale", "Milpitas", "Campbell", "Cupertino"],
    "Santa Clara": ["Santa Clara", "San Jose", "Sunnyvale", "Cupertino"],
    "Cupertino": ["Cupertino", "San Jose", "Sunnyvale", "Santa Clara"],
}


def ensure_geocode_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
          query TEXT PRIMARY KEY,
          latitude REAL,
          longitude REAL,
          display_name TEXT,
          created_at TEXT NOT NULL
        )
        """
    )


def chp_notification_context(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    text = f"{row['title']} {row['content']}"
    if has_out_of_area_hint(text):
        return None
    if not looks_potentially_south_bay(text):
        return None

    queries = extract_chp_location_queries(text)
    if not queries:
        return None

    ensure_geocode_schema(conn)
    geocoded = None
    query = ""
    for candidate_query in queries:
        query = candidate_query
        geocoded = geocode_cached(conn, candidate_query, config)
        if geocoded:
            break
    if not geocoded:
        return None

    center = config.get("locations", {}).get("center", {})
    center_lat = float(center.get("latitude", 37.3382))
    center_lon = float(center.get("longitude", -121.8863))
    radius = float(config.get("locations", {}).get("chp_report_radius_miles", 25))
    distance = haversine_miles(center_lat, center_lon, geocoded["latitude"], geocoded["longitude"])
    if distance > radius:
        return None

    map_path = render_map_image(row["id"], geocoded, config)
    return {
        "query": query,
        "latitude": geocoded["latitude"],
        "longitude": geocoded["longitude"],
        "display_name": geocoded["display_name"],
        "distance_miles": distance,
        "map_path": map_path,
    }


def looks_potentially_south_bay(text: str) -> bool:
    lowered = text.lower()
    if any(place.lower() in lowered for place in LOCALITY_HINTS):
        return True
    if re.search(r"\b(?:I|US|CA|SR|HWY|HIGHWAY|ROUTE)[-\s]*(?:280|880|87|101)\b", text, re.I):
        return True
    return False


def has_out_of_area_hint(text: str) -> bool:
    for locality in OUT_OF_AREA_HINTS:
        if re.search(rf"\b{re.escape(locality)}\b", text, re.I):
            return True
    return False


def extract_chp_location_queries(text: str) -> list[str]:
    compact = " ".join(text.split())
    compact = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b.*$", "", compact)
    city = first_locality(compact)
    location_part = strip_chp_prefix(compact, city)
    normalized = normalize_road_text(location_part)
    queries: list[str] = []
    cities = city_candidates(city)

    for road_name in extract_surface_roads(normalized):
        for city_name in cities:
            queries.append(f"{road_name}, {city_name}, California")

    if city:
        queries.append(f"{normalized}, {city}, California")
        queries.append(f"{city}, California")
    else:
        queries.append(f"{normalized}, California")

    deduped: list[str] = []
    for query in queries:
        query = " ".join(query.split())
        if query and query not in deduped:
            deduped.append(query)
    return deduped


def first_locality(text: str) -> str:
    for locality in LOCALITY_HINTS:
        if re.search(rf"\b{re.escape(locality)}\b", text, re.I):
            return locality
    return ""


def city_candidates(city: str) -> list[str]:
    if not city:
        return ["San Jose", "Santa Clara", "Sunnyvale", "Milpitas", "Cupertino", "Campbell", "Mountain View", "Redwood City"]
    return NEARBY_CITY_FALLBACKS.get(city, [city])


def strip_chp_prefix(text: str, city: str) -> str:
    text = re.sub(r"^CHP Bay Area traffic update\s*", "", text, flags=re.I)
    text = re.sub(r"^CHP Mobile Back CA\.GOV Home Traffic for Bay Area\s*", "", text, flags=re.I)
    text = re.sub(r"^\d{1,2}:\d{2}(?:AM|PM)\s*", "", text, flags=re.I)
    text = re.sub(r"^[A-Z0-9]+-[A-Za-z0-9 -]+\s+", "", text)
    if city:
        match = re.search(rf"\b{re.escape(city)}\b(.+)$", text, re.I)
        if match:
            return f"{city} {match.group(1)}"
    return text


def normalize_road_text(text: str) -> str:
    replacements = {
        r"\bUs(\d+)\b": r"US \1",
        r"\bSr(\d+)\b": r"SR \1",
        r"\bI(\d+)\b": r"I \1",
        r"\bAve\b": "Avenue",
        r"\bBlvd\b": "Boulevard",
        r"\bRd\b": "Road",
        r"\bDr\b": "Drive",
        r"\bLn\b": "Lane",
        r"\bExpy\b": "Expressway",
        r"\bPkwy\b": "Parkway",
        r"\bOfr\b": "off ramp",
        r"\bOnr\b": "on ramp",
        r"\bN\b": "north",
        r"\bS\b": "south",
        r"\bE\b": "east",
        r"\bW\b": "west",
    }
    result = text.replace(" / ", " and ")
    for pattern, value in replacements.items():
        result = re.sub(pattern, value, result, flags=re.I)
    return " ".join(result.split())


def extract_surface_roads(text: str) -> list[str]:
    roads: list[str] = []
    candidates = re.split(r"\band\b|,", text, flags=re.I)
    for candidate in candidates:
        cleaned = re.sub(r"\b(?:I|US|SR|CA)\s*\d+\b", "", candidate, flags=re.I)
        cleaned = re.sub(r"\b(?:north|south|east|west|off ramp|on ramp|con|fsp)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\b(?:San Jose|Santa Clara|Cupertino|Sunnyvale|Milpitas|Campbell|Mountain View|Palo Alto|Los Gatos|Saratoga|Los Altos|Fremont|Newark|Union City|Morgan Hill|Redwood City|Menlo Park|San Mateo|Hayward|Pleasanton)\b", "", cleaned, flags=re.I)
        cleaned = cleaned.lstrip("/- ")
        cleaned = " ".join(cleaned.split())
        if re.search(r"\b(?:Avenue|Boulevard|Road|Drive|Lane|Expressway|Parkway|Street|St)\b", cleaned, re.I):
            roads.append(cleaned)
    return roads


def geocode_cached(
    conn: sqlite3.Connection,
    query: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM geocode_cache WHERE query = ?",
        (query,),
    ).fetchone()
    if row:
        if row["latitude"] is None or row["longitude"] is None:
            return None
        return {
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "display_name": row["display_name"] or query,
        }

    user_agent = config.get("app", {}).get("user_agent", "SouthBayNewsbot/0.1")
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "us",
        },
        headers={"User-Agent": user_agent},
        timeout=10,
        verify=certifi.where(),
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache(query, latitude, longitude, display_name, created_at) VALUES (?, NULL, NULL, ?, ?)",
            (query, "", utc_now_iso()),
        )
        return None
    location = results[0]
    lat = float(location["lat"])
    lon = float(location["lon"])
    display_name = location.get("display_name", query)

    conn.execute(
        "INSERT OR REPLACE INTO geocode_cache(query, latitude, longitude, display_name, created_at) VALUES (?, ?, ?, ?, ?)",
        (query, lat, lon, display_name, utc_now_iso()),
    )
    return {
        "latitude": lat,
        "longitude": lon,
        "display_name": display_name,
    }


def render_map_image(raw_item_id: int, geocoded: dict[str, Any], config: dict[str, Any]) -> str:
    root = Path(config.get("runtime", {}).get("map_dir", "/Users/chuxuanfu/newsbot/data/maps"))
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{raw_item_id}:{geocoded['latitude']}:{geocoded['longitude']}".encode()).hexdigest()[:12]
    path = root / f"chp_{raw_item_id}_{digest}.png"
    static_map = StaticMap(
        800,
        520,
        url_template="https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
    )
    static_map.add_marker(CircleMarker((geocoded["longitude"], geocoded["latitude"]), "red", 18))
    image = static_map.render(zoom=13)
    image.save(path)
    return str(path)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
