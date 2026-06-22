from __future__ import annotations

import requests


def get_text(url: str, user_agent: str, timeout: int = 30) -> str:
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def get_json(url: str, user_agent: str, timeout: int = 30) -> dict:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def get_bytes(url: str, user_agent: str, timeout: int = 60) -> bytes:
    headers = {"User-Agent": user_agent}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.content
