from __future__ import annotations

import re
from typing import Any


def text_blob(row: dict[str, Any]) -> str:
    return " ".join([
        str(row.get("title", "")),
        str(row.get("content", "")),
        str(row.get("category_hint", "")),
    ])


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    lowered = text.lower()
    for keyword in keywords:
        keyword_text = str(keyword)
        if keyword_text.lower() in lowered:
            hits.append(keyword_text)
    return hits


def configured_location_hits(text: str, config: dict[str, Any]) -> list[str]:
    locations = config.get("locations", {})
    candidates: list[str] = []
    candidates.extend(str(city) for city in locations.get("cities", []))
    for canonical, aliases in locations.get("aliases", {}).items():
        candidates.append(str(canonical))
        candidates.extend(str(alias) for alias in aliases or [])
    hits = set(keyword_hits(text, candidates))
    hits.update(road_hits(text, [str(road) for road in locations.get("roads", [])]))
    return sorted(hits)


def road_hits(text: str, roads: list[str]) -> list[str]:
    hits: list[str] = []
    for road in roads:
        road_text = road.upper()
        normalized = road_text.replace("INTERSTATE", "I").replace("HIGHWAY", "HWY")
        match = re.search(r"([0-9]{1,3})", normalized)
        if not match:
            if road_text.lower() in text.lower():
                hits.append(road)
            continue
        number = match.group(1)
        prefixed = re.compile(rf"\b(?:I|US|CA|SR|HWY|HIGHWAY|ROUTE)[-\s]*{number}\b", re.I)
        bare = re.compile(rf"\b{number}\b(?!\s*(?:km|kilometer|kilometers|mi|mile|miles|meter|meters)\b)", re.I)
        if prefixed.search(text) or bare.search(text):
            hits.append(road)
    return hits


def rule_prefilter(row: dict[str, Any], config: dict[str, Any]) -> bool:
    text = text_blob(row)
    topics = config.get("topics", {})
    if configured_location_hits(text, config):
        return True
    if keyword_hits(text, topics.get("high", [])):
        return True
    if row.get("category_hint") in {
        "traffic",
        "weather",
        "earthquake",
        "fire",
        "layoff",
        "immigration",
    }:
        return True
    return False


def clamp_score(value: float) -> float:
    return max(0.0, min(10.0, float(value)))


def merge_rule_scores(result: dict[str, Any], row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    text = text_blob(row)
    loc_hits = configured_location_hits(text, config)
    topic_hits = keyword_hits(text, config.get("topics", {}).get("high", []))
    noise_hits = keyword_hits(text, config.get("topics", {}).get("noise", []))
    category_hint = row.get("category_hint") or ""

    if loc_hits:
        result["locations"] = sorted(set((result.get("locations") or []) + loc_hits))
        result["relevance_score"] = max(float(result.get("relevance_score", 0)), 7.0)
    if topic_hits:
        result["relevance_score"] = max(float(result.get("relevance_score", 0)), 6.0)
    if category_hint in {"traffic", "weather", "earthquake", "fire"}:
        result["urgency_score"] = max(float(result.get("urgency_score", 0)), 6.0)
        result["credibility_score"] = max(float(result.get("credibility_score", 0)), 6.0)
    if category_hint in {"layoff", "immigration"}:
        result["relevance_score"] = max(float(result.get("relevance_score", 0)), 6.0)
    if noise_hits and not loc_hits:
        result["noise_score"] = max(float(result.get("noise_score", 0)), 6.0)

    category = str(result.get("category") or category_hint or "local").lower()
    if "earthquake" in text.lower():
        category = "earthquake"
    elif any(k in text.lower() for k in ["collision", "crash", "sigalert", "lane", "traffic"]):
        category = "traffic"
    elif any(k in text.lower() for k in ["wildfire", "evacuation", "smoke", "fire"]):
        category = "fire"
    elif any(k in text.lower() for k in ["uscis", "visa bulletin", "h1b", "perm", "eb2", "eb3"]):
        category = "immigration"
    elif any(k in text.lower() for k in ["warn", "layoff", "oracle", "oci"]):
        category = "layoff"
    result["category"] = category

    for key in ["urgency_score", "relevance_score", "credibility_score", "noise_score"]:
        result[key] = clamp_score(float(result.get(key, 0) or 0))

    result["final_priority"] = final_priority(result)
    return result


def final_priority(result: dict[str, Any]) -> float:
    relevance = clamp_score(result.get("relevance_score", 0))
    urgency = clamp_score(result.get("urgency_score", 0))
    credibility = clamp_score(result.get("credibility_score", 0))
    noise = clamp_score(result.get("noise_score", 0))
    priority = (
        relevance * 0.35
        + urgency * 0.30
        + credibility * 0.20
        - noise * 0.25
    )
    return round(max(0.0, min(10.0, priority)), 2)


def token_similarity(left: str, right: str) -> float:
    def tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9]+", value.lower())
            if len(token) > 2
        }

    a = tokens(left)
    b = tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
