from __future__ import annotations

import re
from typing import Any

import requests

from app.config import env_value


def should_summarize(row: dict[str, Any] | Any) -> bool:
    source_type = row["source_type"]
    category_hint = row["category_hint"] or ""
    return source_type in {"reddit_json", "rss"} or category_hint in {"local_news"}


def summarize_for_notification(row: dict[str, Any] | Any, config: dict[str, Any]) -> str:
    title = str(row["title"] or "")
    content = str(row["content"] or "")
    url = str(row["item_url"] or row["source_url"] or "")
    if not should_summarize(row):
        return ""
    try:
        summary = ollama_summary(title, content, url, config)
        summary = strip_thinking(summary).strip()
        if not is_mostly_chinese(summary):
            summary = strip_thinking(ollama_force_chinese(summary, title, content, config)).strip()
        if is_mostly_chinese(summary):
            return summary
    except Exception:
        pass
    try:
        summary = strip_thinking(ollama_force_chinese("", title, content, config)).strip()
        if is_mostly_chinese(summary):
            return summary
    except Exception:
        fallback = " ".join([title, content[:300]]).strip()
        return f"摘要生成失败，原文：{fallback[:450]}"
    fallback = " ".join([title, content[:300]]).strip()
    return f"摘要生成失败，原文：{fallback[:450]}"


def ollama_summary(title: str, content: str, url: str, config: dict[str, Any]) -> str:
    classifier = config.get("classifier", {})
    base_url = env_value(classifier.get("ollama_base_url_env"), "http://127.0.0.1:11434")
    model = env_value(classifier.get("ollama_model_env"), "llama3.1:8b")
    prompt = f"""
你必须只用简体中文输出。请用简体中文总结下面这条新信息，要求：
1. 简洁准确，最多 3 句话。
2. 不输出英文摘要，不输出推理过程，不输出 thinking，不使用 <think> 标签。
3. 如果只是网友提问或传闻，要明确说“未确认”。
4. 不要夸大，不要补充原文没有的信息。

标题：{title}
内容：{content[:3000]}
网址：{url}
"""
    response = requests.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 180,
            },
        },
        timeout=int(classifier.get("timeout_seconds", 60)),
    )
    response.raise_for_status()
    return str(response.json().get("response", ""))


def ollama_force_chinese(summary: str, title: str, content: str, config: dict[str, Any]) -> str:
    classifier = config.get("classifier", {})
    base_url = env_value(classifier.get("ollama_base_url_env"), "http://127.0.0.1:11434")
    model = env_value(classifier.get("ollama_model_env"), "llama3.1:8b")
    prompt = f"""
你必须只用简体中文输出，不能输出英文。
请把下面内容改写成最多 3 句简体中文新闻摘要。
不要输出推理过程，不要输出 <think>。

已有摘要：{summary}
标题：{title}
内容：{content[:3000]}
"""
    response = requests.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 180,
            },
        },
        timeout=int(classifier.get("timeout_seconds", 60)),
    )
    response.raise_for_status()
    return str(response.json().get("response", ""))


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"(?is)^\\s*thinking:.*", "", text)
    return text.strip()


def is_mostly_chinese(text: str) -> bool:
    if not text.strip():
        return False
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    return chinese >= 8 and chinese >= letters * 0.35
