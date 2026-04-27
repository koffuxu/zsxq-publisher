#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Link an existing article to a topic in the current group.

This is a small helper for cases where /v2/articles succeeded but the topic
creation step failed (rate limiting / transient errors).
"""

import argparse
import json
import time
from typing import List, Optional

import requests

from auth import load_auth, build_request_headers
from config import ENDPOINTS
from markdown_converter import (
    extract_title_from_markdown,
    markdown_to_topic_text,
    format_hashtags,
)


def _parse_tags(tags: Optional[str]) -> Optional[List[str]]:
    if not tags:
        return None
    items = [t.strip() for t in tags.split(",")]
    items = [t for t in items if t]
    return items or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-id", required=True, help="Existing article_id")
    ap.add_argument("--file", required=True, help="Markdown file used to build summary")
    ap.add_argument("--tags", default="", help="Comma-separated tags")
    ap.add_argument("--retries", type=int, default=5)
    args = ap.parse_args()

    from pathlib import Path

    md_path = Path(args.file)
    md_content = md_path.read_text(encoding="utf-8")
    title, body = extract_title_from_markdown(md_content)
    if not title:
        title = md_path.stem

    summary = body[:200] if body else ""
    topic_text = markdown_to_topic_text(summary, title=title)

    tags = _parse_tags(args.tags)
    if tags:
        topic_text += "\n" + format_hashtags(tags)

    payload = {
        "req_data": {
            "type": "talk",
            "text": topic_text,
            "article_id": args.article_id,
        }
    }

    cookies, base_headers = load_auth()
    headers = build_request_headers(base_headers)

    last = None
    for attempt in range(1, max(1, args.retries) + 1):
        resp = requests.post(
            ENDPOINTS["create_topic"],
            headers=headers,
            cookies=cookies,
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            last = {"succeeded": False, "http_status": resp.status_code, "text": resp.text}
        else:
            last = resp.json()

        if isinstance(last, dict) and last.get("succeeded"):
            topic = (last.get("resp_data") or {}).get("topic") or {}
            print("[OK] linked")
            print("topic_id:", topic.get("topic_id"))
            print("article_id:", args.article_id)
            return 0

        code = last.get("code") if isinstance(last, dict) else None
        if code in (429, 1059):
            sleep_s = min(30, 4 * attempt)
            time.sleep(sleep_s)
            continue

        print("[FAIL] link failed:", json.dumps(last, ensure_ascii=False))
        return 2

    print("[FAIL] link failed after retries:", json.dumps(last, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

