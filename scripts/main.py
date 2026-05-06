#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识星球发布工具 - 主入口

用法:
  main.py setup                          首次配置（通过 zsxq-cli auth login）
  main.py login                          浏览器登录授权
  main.py check-auth                    检查认证状态
  main.py publish --file <path>         发布文件（自动判断话题/文章）
  main.py topic --text <text> [--tags t] 发布话题（短内容）
  main.py article --file <path>         发布文章（长内容，带图）
  main.py history                        查看发布历史

日常操作优先委托给 zsxq-cli 官方 skill；仅文章发布（两步流程+图片）由本工具自持。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from publisher import ZsxqPublisher


# ── zsxq-cli 代理 ──────────────────────────────────────────────

def _sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


# ── 命令实现 ─────────────────────────────────────────────────

def cmd_setup(args):
    print("zsxq-publisher 已重构为基于 zsxq-cli 的发布工具。")
    print("认证请直接运行: zsxq-cli auth login")
    print("配置 group_id 请运行: zsxq-cli group +list")
    return 0


def cmd_login(args):
    """启动浏览器登录（通过 zsxq-cli auth login）"""
    p = _sh(["zsxq-cli", "auth", "login"])
    if p.returncode == 0:
        print("[OK] 登录成功")
        return 0
    else:
        print(f"[FAIL] 登录失败: {p.stderr}")
        return 1


def cmd_check_auth(args):
    """检查认证状态"""
    from auth import check_auth
    ok, msg = check_auth()
    if ok:
        print(f"[OK] 已登录：{msg}")
        return 0
    else:
        print(f"[FAIL] 未登录：{msg}")
        print("提示: zsxq-cli auth login")
        return 1


def cmd_publish(args):
    """发布文件（自动判断模式）"""
    from publisher import api_raw, markdown_to_topic_text, format_hashtags, extract_title_from_markdown, markdown_to_article_html
    import time, random

    md_text = Path(args.file).read_text(encoding="utf-8")
    tags = args.tags.split(",") if args.tags else None

    # 简单判断：超过 500 字视为文章
    if len(md_text) >= 500:
        return cmd_article_argparse(Path(args.file).read_text(encoding="utf-8"), args.title or "", tags)

    # 短内容：直接用 zsxq-cli topic +create
    title, body = extract_title_from_markdown(md_text)
    topic_text = markdown_to_topic_text(body or md_text, title=title or args.title or "")
    if tags:
        topic_text += "\n" + format_hashtags(tags)

    p = _sh(["zsxq-cli", "group", "+list", "--json"])
    if p.returncode != 0:
        print("[FAIL] 无法获取 group 列表")
        return 1
    data = json.loads(p.stdout)
    groups = data.get("groups", []) or []
    if not groups:
        print("[FAIL] 未找到任何星球")
        return 1
    gid = str(groups[0].get("group_id", ""))

    out = _sh([
        "zsxq-cli", "topic", "+create",
        "--group-id", gid,
        "--title", title or args.title or "",
        "--content", topic_text,
        "--json",
    ])
    if p.returncode == 0:
        print("[OK] 话题发布成功")
        return 0
    else:
        print(f"[FAIL] {out.stderr or out.stdout}")
        return 1


def cmd_topic(args):
    """发布话题"""
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        print("[error] 请提供 --text 或 --file")
        return 1

    # 获取默认 group
    p = _sh(["zsxq-cli", "group", "+list", "--json"])
    if p.returncode != 0:
        print("[FAIL] 无法获取 group 列表")
        return 1
    data = json.loads(p.stdout)
    groups = data.get("groups", []) or []
    if not groups:
        print("[FAIL] 未找到任何星球")
        return 1
    gid = str(groups[0].get("group_id", ""))

    title = args.title or ""
    tags = args.tags.split(",") if args.tags else None

    out = _sh([
        "zsxq-cli", "topic", "+create",
        "--group-id", gid,
        "--title", title,
        "--content", text,
        "--json",
    ])
    if out.returncode == 0:
        print("[OK] 话题发布成功")
        return 0
    else:
        print(f"[FAIL] {out.stderr or out.stdout}")
        return 1


def cmd_article(args):
    """发布文章（长内容，两步流程）"""
    if not args.file:
        print("[error] 请提供 --file 参数")
        return 1

    md_content = Path(args.file).read_text(encoding="utf-8")
    title = args.title or ""
    tags = args.tags.split(",") if args.tags else None
    image_path = Path(args.image) if getattr(args, "image", None) else None
    base_dir = Path(args.file).parent

    # 如果没指定 group_id，使用配置文件中的默认群组
    group_id = args.group_id if getattr(args, "group_id", None) else None

    pub = ZsxqPublisher()
    result = pub.publish_article(
        md_content=md_content,
        title=title,
        group_id=group_id or "",
        tags=tags,
        image_path=image_path,
        base_dir=base_dir,
    )

    if result.get("succeeded"):
        print(f"[OK] 文章发布成功")
        print(f"  article_id: {result.get('article_id')}")
        print(f"  article_url: {result.get('article_url')}")
        if result.get("topic_id"):
            print(f"  topic_id: {result.get('topic_id')}")
        return 0
    else:
        print(f"[FAIL] {json.dumps(result, ensure_ascii=False)[:300]}")
        return 1


def cmd_history(args):
    """查看发布历史（通过 zsxq-cli topic +search）"""
    print("zsxq-publisher 暂不维护本地发布历史。")
    print("可用 zsxq-cli topic +search <keyword> 查询历史主题。")
    return 0


# ── 主入口 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="知识星球内容发布工具（基于 zsxq-cli）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    sub.add_parser("setup", help="查看配置说明").set_defaults(func=cmd_setup)
    sub.add_parser("login", help="浏览器登录授权").set_defaults(func=cmd_login)
    sub.add_parser("check-auth", help="检查认证状态").set_defaults(func=cmd_check_auth)
    sub.add_parser("history", help="查看发布历史").set_defaults(func=cmd_history)

    p_pub = sub.add_parser("publish", help="发布文件（自动判断话题/文章）")
    p_pub.add_argument("--file", "-f", required=True)
    p_pub.add_argument("--tags", "-t")
    p_pub.set_defaults(func=cmd_publish)

    p_topic = sub.add_parser("topic", help="发布话题（短内容）")
    p_topic.add_argument("--text")
    p_topic.add_argument("--file", "-f")
    p_topic.add_argument("--title")
    p_topic.add_argument("--tags", "-t")
    p_topic.set_defaults(func=cmd_topic)

    p_art = sub.add_parser("article", help="发布文章（长内容）")
    p_art.add_argument("--file", "-f", required=True)
    p_art.add_argument("--title")
    p_art.add_argument("--tags", "-t")
    p_art.add_argument("--image")
    p_art.add_argument("--group-id", "-g")
    p_art.set_defaults(func=cmd_article)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())