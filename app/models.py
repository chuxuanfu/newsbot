from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RawItem:
    source_name: str
    source_type: str
    source_url: str
    title: str
    content: str = ""
    item_url: str = ""
    author: str = ""
    published_at: str = ""
    fetched_at: str = field(default_factory=utc_now_iso)
    raw: dict[str, Any] = field(default_factory=dict)
    category_hint: str = ""


@dataclass
class Candidate:
    raw_item_id: int
    is_event: bool
    category: str
    locations: list[str]
    entities: list[str]
    urgency_score: float
    relevance_score: float
    credibility_score: float
    noise_score: float
    summary: str
    why_it_matters: str
    action_needed: str
    confidence_reason: str
    final_priority: float

