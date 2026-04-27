#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

import requests

from auth import build_request_headers, load_auth
from markdown_converter import markdown_to_topic_text


API_BASE = "https://api.zsxq.com/v2"


def post_topic(group_id: str, title: str, body: str) -> None:
    cookies, base_headers = load_auth()
    headers = build_request_headers(base_headers)
    url = f"{API_BASE}/groups/{group_id}/topics"
    payload = {"req_data": {"type": "talk", "text": markdown_to_topic_text(body, title)}}

    print(f"== POST topic {group_id} ==")
    resp = requests.post(url, headers=headers, cookies=cookies, json=payload, timeout=30)
    print(f"status={resp.status_code}")
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(resp.text)


def get_hashtags(group_id: str) -> None:
    cookies, base_headers = load_auth()
    headers = build_request_headers(base_headers)
    url = f"{API_BASE}/users/self/groups/{group_id}/hashtags"

    print(f"== GET hashtags {group_id} ==")
    resp = requests.get(url, headers=headers, cookies=cookies, timeout=30)
    print(f"status={resp.status_code}")
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(resp.text)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: diagnose_group.py <group_id> [mode] [file]")
        return 1

    group_id = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "both"
    file_path = sys.argv[3] if len(sys.argv) > 3 else ""

    if file_path:
        raw = Path(file_path).read_text(encoding="utf-8")
        title = Path(file_path).stem
        body = raw
    else:
        title = "诊断发布测试"
        body = "这是一条用于排查知识星球发布权限和接口兼容性的诊断消息。"

    if mode in ("hashtags", "both"):
        get_hashtags(group_id)
    if mode in ("topic", "both"):
        post_topic(group_id, title, body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
