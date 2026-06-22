from __future__ import annotations

import json
import os
import re
from typing import Any

import requests
from openai import OpenAI

from app.config import env_value
from app.models import Candidate
from app.scoring import final_priority, merge_rule_scores, rule_prefilter


SYSTEM_PROMPT = """You are an event triage classifier for a personal South Bay event radar.
Return strict JSON only. Do not include markdown.
Decide whether the input describes a concrete, time-sensitive event or useful monitored update.
Focus on San Jose, Cupertino, Santa Clara, I-280, I-880, CA-87, US-101, local safety,
traffic, weather, fire, earthquake, immigration, Oracle/OCI layoffs, and WARN notices.
AI is not a fact source: express credibility based only on source type and evidence in the item.
"""


def user_prompt(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "source_name": row.get("source_name"),
            "source_type": row.get("source_type"),
            "category_hint": row.get("category_hint"),
            "title": row.get("title"),
            "content": row.get("content"),
            "published_at": row.get("published_at"),
            "item_url": row.get("item_url"),
        },
        ensure_ascii=False,
    )


def classify_row(row: dict[str, Any], config: dict[str, Any]) -> Candidate:
    if not rule_prefilter(row, config):
        result = fallback_result(row, is_event=False)
    elif should_use_fast_trusted_classifier(row):
        result = fallback_result(row, is_event=True)
    else:
        result = classify_with_provider(row, config)
    result = normalize_result(result)
    result = merge_rule_scores(result, row, config)
    return Candidate(
        raw_item_id=int(row["id"]),
        is_event=bool(result.get("is_event")),
        category=str(result.get("category") or "local"),
        locations=list(result.get("locations") or []),
        entities=list(result.get("entities") or []),
        urgency_score=float(result.get("urgency_score", 0)),
        relevance_score=float(result.get("relevance_score", 0)),
        credibility_score=float(result.get("credibility_score", 0)),
        noise_score=float(result.get("noise_score", 0)),
        summary=str(result.get("summary") or row.get("title") or ""),
        why_it_matters=str(result.get("why_it_matters") or ""),
        action_needed=str(result.get("action_needed") or ""),
        confidence_reason=str(result.get("confidence_reason") or ""),
        final_priority=float(result.get("final_priority") or final_priority(result)),
    )


def should_use_fast_trusted_classifier(row: dict[str, Any]) -> bool:
    source_type = row.get("source_type") or ""
    category_hint = row.get("category_hint") or ""
    return source_type in {
        "chp_html",
        "nws_alerts",
        "usgs_geojson",
        "calfire_json",
        "warn_xlsx",
    } or category_hint in {
        "traffic",
        "weather",
        "earthquake",
        "fire",
    }


def classify_with_provider(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    classifier = config.get("classifier", {})
    provider = classifier.get("provider", "ollama")
    try:
        if provider == "openai":
            return classify_openai(row, config)
        return classify_ollama(row, config)
    except Exception as exc:
        if provider != "openai" and classifier.get("use_openai_fallback"):
            if os.environ.get("OPENAI_API_KEY"):
                try:
                    return classify_openai(row, config)
                except Exception:
                    pass
        result = fallback_result(row, is_event=True)
        result["confidence_reason"] = f"LLM failed; used rule fallback: {exc}"
        return result


def classify_ollama(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    classifier = config.get("classifier", {})
    base_url = env_value(classifier.get("ollama_base_url_env"), "http://127.0.0.1:11434")
    model = env_value(classifier.get("ollama_model_env"), "llama3.1:8b")
    response = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(row) + "\n\nSchema: " + schema_text()},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        },
        timeout=int(classifier.get("timeout_seconds", 60)),
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    return parse_json_object(content)


def classify_openai(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    classifier = config.get("classifier", {})
    model = env_value(classifier.get("openai_model_env"), "gpt-4.1-mini")
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(row) + "\n\nSchema: " + schema_text()},
        ],
    )
    return parse_json_object(response.choices[0].message.content or "{}")


def schema_text() -> str:
    return json.dumps(
        {
            "is_event": "boolean",
            "category": "traffic|safety|weather|fire|earthquake|immigration|layoff|local|local_news|noise",
            "locations": ["string"],
            "entities": ["string"],
            "urgency_score": "0-10 number",
            "relevance_score": "0-10 number",
            "credibility_score": "0-10 number",
            "noise_score": "0-10 number",
            "summary": "short factual summary",
            "why_it_matters": "why this matters to the user",
            "action_needed": "specific action or empty string",
            "confidence_reason": "source/evidence basis",
        },
        ensure_ascii=False,
    )


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "is_event": False,
        "category": "local",
        "locations": [],
        "entities": [],
        "urgency_score": 0,
        "relevance_score": 0,
        "credibility_score": 0,
        "noise_score": 0,
        "summary": "",
        "why_it_matters": "",
        "action_needed": "",
        "confidence_reason": "",
    }
    defaults.update(result or {})
    if not isinstance(defaults["locations"], list):
        defaults["locations"] = [str(defaults["locations"])]
    if not isinstance(defaults["entities"], list):
        defaults["entities"] = [str(defaults["entities"])]
    return defaults


def fallback_result(row: dict[str, Any], is_event: bool) -> dict[str, Any]:
    hint = row.get("category_hint") or "local"
    source_type = row.get("source_type") or ""
    credibility = 6 if source_type in {"nws_alerts", "usgs_geojson", "calfire_json", "chp_html", "warn_xlsx"} else 4
    return {
        "is_event": is_event,
        "category": hint,
        "locations": [],
        "entities": [],
        "urgency_score": 4 if is_event else 0,
        "relevance_score": 4 if is_event else 0,
        "credibility_score": credibility if is_event else 0,
        "noise_score": 2 if is_event else 7,
        "summary": row.get("title") or "",
        "why_it_matters": "",
        "action_needed": "",
        "confidence_reason": "Rule-based fallback.",
    }
