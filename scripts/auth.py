#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识星球发布工具 - 认证模块

基于 zsxq-cli（官方 OpenClaw skill）认证，不再依赖 auth.json。
认证状态由 zsxq-cli 自身管理（Keychain）。
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from typing import Any, Dict, Tuple


# ── 底层调用 zsxq-cli ───────────────────────────────────────────

def _sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"zsxq-cli failed: {' '.join(cmd)}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p.stdout


def auth_status() -> Dict[str, Any]:
    """通过 zsxq-cli 检查登录状态"""
    out = _sh(["zsxq-cli", "auth", "status", "--json"])
    return json.loads(out)


def check_auth() -> Tuple[bool, str]:
    """返回 (is_logged_in, user_name_or_reason)"""
    try:
        data = auth_status()
        if data.get("ok") and (data.get("data") or {}).get("loggedIn"):
            user = (data.get("data") or {}).get("userName", "?")
            return True, user
        return False, "未登录或登录已过期"
    except Exception as e:
        return False, str(e)


def ensure_auth() -> None:
    """确保已登录，未登录则抛出异常提示"""
    ok, msg = check_auth()
    if not ok:
        raise RuntimeError(
            f"知识星球未登录：{msg}\n"
            "请先运行：zsxq-cli auth login\n"
            "或在 OpenClaw 中使用 zsxq-shared skill 的 login 流程。"
        )


# ── 保留给旧兼容的 build_request_headers（当前不再需要）──────

API_VERSION = "2.89.0"


def build_request_headers(base_headers: Dict[str, str]) -> Dict[str, str]:
    """构建请求头（兼容旧代码，zsxq-publisher 内部已不直接使用）"""
    timestamp = str(int(time.time()))
    request_id = f"{uuid.uuid4().hex[:9]}-{uuid.uuid4().hex[9:13]}-{uuid.uuid4().hex[13:17]}-{uuid.uuid4().hex[17:21]}-{uuid.uuid4().hex[21:32]}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://wx.zsxq.com",
        "referer": "https://wx.zsxq.com/",
        "x-request-id": request_id,
        "x-version": API_VERSION,
        "x-timestamp": timestamp,
    }
    if base_headers.get("User-Agent"):
        headers["user-agent"] = base_headers["User-Agent"]
    if base_headers.get("Referer"):
        headers["referer"] = base_headers["Referer"]
    return headers


def check_auth_status(cookies=None, headers=None) -> bool:
    """兼容旧接口，直接透传到 zsxq-cli auth status"""
    ok, _ = check_auth()
    return ok


# ── 对外：检查认证（供 main.py check-auth 使用）──────────────

def load_auth():
    """兼容旧接口：返回 (cookies_dict, headers_dict)
    实际认证已由 zsxq-cli 管理，此处仅做占位返回"""
    ensure_auth()
    return {}, {}