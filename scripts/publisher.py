#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识星球发布工具 - 发布模块

发布模式：
1. 话题发布（短内容）：POST /v2/groups/{group_id}/topics
2. 文章发布（长内容）：先 POST /v2/articles 创建文章，再 POST topics 引用文章

内部实现：底层通过 zsxq-cli api raw 调用官方 API，不再依赖 auth.json。
"""

from __future__ import annotations

import json
import mimetypes
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


def _sh(cmd: List[str]) -> str:
    """执行 shell 命令，失败则抛异常"""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p.stdout


# ── zsxq-cli 封装层 ────────────────────────────────────────────

def auth_status() -> Dict[str, Any]:
    """通过 zsxq-cli 检查登录状态"""
    out = _sh(["zsxq-cli", "auth", "status", "--json"])
    return json.loads(out)


def ensure_auth() -> None:
    """确保已登录，未登录则抛出异常提示"""
    data = auth_status()
    if not ((data.get("ok") is True) and ((data.get("data") or {}).get("loggedIn") is True)):
        raise RuntimeError(
            "未登录知识星球，请先运行：zsxq-cli auth login\n"
            "或在 Skill 环境中使用 zsxq-shared 技能的 login 流程。"
        )


def api_call(tool: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """通过 zsxq-cli 调用 MCP 工具"""
    cmd = ["zsxq-cli", "api", "call", tool]
    if params:
        cmd += ["--params", json.dumps(params, ensure_ascii=False)]
    out = _sh(cmd)
    data = json.loads(out)
    return data.get("result", {}).get("body", {})


def api_raw(method: str, path: str, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """通过 zsxq-cli raw 调用 API（灵活调用任意端点）"""
    cmd = ["zsxq-cli", "api", "raw", "--method", method, "--path", path]
    if body is not None:
        cmd += ["--body", json.dumps(body, ensure_ascii=False)]
    if query is not None:
        cmd += ["--query", json.dumps(query, ensure_ascii=False)]
    out = _sh(cmd)
    data = json.loads(out)
    return data.get("result", {}).get("body", {})


def get_upload_token() -> str:
    """申请七牛云图片上传 token（通过官方 upload 端点）"""
    body = api_raw("POST", "/v2/uploads", {
        "req_data": {"type": "image", "usage": "article", "name": "", "hash": "", "size": ""}
    })
    token = ((body.get("resp_data") or {}).get("upload_token"))
    if not token:
        raise RuntimeError(f"获取 upload_token 失败: {json.dumps(body, ensure_ascii=False)[:300]}")
    return token


def upload_image(image_path: Path) -> Dict[str, Any]:
    """上传单张图片到知识星球 CDN，返回 image_id 和 url"""
    token = get_upload_token()
    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "application/octet-stream"
    files = {"file": (image_path.name, image_path.read_bytes(), mime_type)}
    resp = requests.post("https://upload-z1.qiniup.com/", files=files, data={"token": token}, timeout=120)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("succeeded"):
        raise RuntimeError(f"图片上传失败: {json.dumps(body, ensure_ascii=False)[:300]}")
    return {
        "image_id": body["resp_data"]["image_id"],
        "url": body.get("link", ""),
    }


# ── Markdown 转换 ────────────────────────────────────────────

def markdown_to_article_html(md_text: str) -> str:
    """将 Markdown 转换为知识星球文章 HTML（简化版）"""
    html: List[str] = []
    in_ul = False
    for raw in md_text.splitlines():
        line = raw.strip()
        if not line:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            continue
        if line.startswith("# "):
            if in_ul:
                html.append("</ul>")
                in_ul = False
            html.append(f"<h1>{line[2:].strip()}</h1>")
        elif line.startswith("## "):
            if in_ul:
                html.append("</ul>")
                in_ul = False
            html.append(f"<h2>{line[3:].strip()}</h2>")
        elif line.startswith("- "):
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            html.append(f"<li>{line[2:].strip()}</li>")
        else:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            html.append(f"<p>{line}</p>")
    if in_ul:
        html.append("</ul>")
    return "\n".join(html)


def markdown_to_topic_text(md_text: str, title: str = "") -> str:
    """将 Markdown 转为知识星球话题纯文本（保留结构和标签）"""
    lines = []
    if title:
        lines.append(f"**{title}**\n")
    for raw in md_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            lines.append(f"• {line[2:].strip()}")
        else:
            lines.append(line)
    return "\n".join(lines)


def extract_title_from_markdown(md_text: str) -> Tuple[str, str]:
    """从 Markdown 中提取标题和正文"""
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = m.group(1).strip() if m else "未命名"
    body = re.sub(r"^#.+\n", "", md_text, count=1).strip()
    return title, body


def format_hashtags(tags: List[str]) -> str:
    return " ".join(f"#{t}" for t in tags)


# ── 发布器 ──────────────────────────────────────────────────

class ZsxqPublisher:
    """知识星球内容发布器（基于 zsxq-cli）"""

    def __init__(self):
        ensure_auth()  # 初始化时即检查认证

    def publish_topic(
        self,
        text: str,
        title: str = "",
        group_id: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """发布话题（短内容）

        Args:
            text: 话题正文
            title: 可选标题（加粗显示）
            group_id: 目标星球 ID，不填则使用默认
            tags: 可选标签列表
        Returns:
            API 响应数据（含 topic_id）
        """
        topic_text = markdown_to_topic_text(text, title=title)
        if tags:
            topic_text += "\n" + format_hashtags(tags)

        gid = group_id or self._get_default_group_id()
        payload = {"req_data": {"type": "talk", "text": topic_text}}

        result = api_raw("POST", f"/v2/groups/{gid}/topics", body=payload)

        if result and result.get("succeeded"):
            topic_data = ((result.get("resp_data") or {}).get("topic") or {})
            print(f"  [OK] 话题发布成功 topic_id={topic_data.get('topic_id')}")
        else:
            print(f"  [FAIL] 话题发布失败: {json.dumps(result, ensure_ascii=False)[:300]}")

        return result or {}

    def publish_article(
        self,
        md_content: str,
        title: str = "",
        group_id: str = "",
        tags: Optional[List[str]] = None,
        image_path: Optional[Path] = None,
        base_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """发布文章（长内容，两步流程）

        Step 1: POST /v2/articles 创建文章（含图片上传）
        Step 2: POST /v2/groups/{id}/topics 创建引用文章的主题

        Args:
            md_content: Markdown 格式文章内容
            title: 文章标题（默认从 Markdown 提取）
            group_id: 目标星球 ID，不填则使用默认
            tags: 可选标签列表
            image_path: 可选本地长图路径（会先上传到 CDN 再插入文章）
            base_dir: 本地图片基准目录
        Returns:
            API 响应（含 article_id、topic_id）
        """
        # 提取标题和正文
        if not title:
            title, body = extract_title_from_markdown(md_content)
        else:
            _, body = extract_title_from_markdown(md_content)

        if not title:
            title = "未命名文章"

        gid = group_id or self._get_default_group_id()
        image_ids: List[int] = []
        image_url: Optional[str] = None

        # Step 0: 处理配图（可选）
        if image_path and Path(image_path).exists():
            print(f"  [图] 上传长图...")
            up = upload_image(Path(image_path))
            image_ids.append(up["image_id"])
            image_url = up.get("url")
            print(f"  [OK] 图片已上传 image_id={up['image_id']} url={image_url}")

        # Step 0b: 处理 md_content 里的图片引用（如果有）
        if base_dir:
            md_content, extra_ids = self._process_md_images(md_content, Path(base_dir))
            image_ids.extend(extra_ids)

        # Step 1: 创建文章
        print(f"  [Step 1] 创建文章 '{title}'...")
        article_html = markdown_to_article_html(md_content)
        article_payload = {
            "req_data": {
                "group_id": gid,
                "title": title,
                "content": article_html,
                "original_content": md_content,
                "image_ids": image_ids,
            }
        }

        article_result = None
        for attempt in range(1, 6):
            article_result = api_raw("POST", "/v2/articles", body=article_payload)
            if article_result and article_result.get("succeeded"):
                break
            code = (article_result or {}).get("code")
            if code in (429, 1059) or article_result is None:
                print(f"    创建文章瞬时失败(code={code})，第{attempt}次重试...")
                time.sleep(min(12.0, 2.5 * attempt))
                continue
            break

        if not article_result or not article_result.get("succeeded"):
            print(f"  [FAIL] 文章创建失败: {json.dumps(article_result, ensure_ascii=False)[:300]}")
            return article_result or {}

        article_data = article_result.get("resp_data") or {}
        article_id = article_data.get("article_id")
        article_url = article_data.get("article_url")
        print(f"  [OK] 文章已创建 article_id={article_id} url={article_url}")

        # 适当延迟
        time.sleep(random.uniform(0.5, 1.5))

        # Step 2: 创建话题引用文章
        print(f"  [Step 2] 创建话题引用文章...")
        summary = body[:300] if body else ""
        topic_text = markdown_to_topic_text(summary, title=title)
        if tags:
            topic_text += "\n" + format_hashtags(tags)

        topic_payload = {
            "req_data": {
                "type": "talk",
                "text": topic_text,
                "article_id": article_id,
            }
        }

        topic_result = None
        for attempt in range(1, 6):
            topic_result = api_raw("POST", f"/v2/groups/{gid}/topics", body=topic_payload)
            if topic_result and topic_result.get("succeeded"):
                break
            code = (topic_result or {}).get("code")
            if code in (429, 1059) or topic_result is None:
                time.sleep(min(12.0, 2.5 * attempt))
                continue
            break

        if not topic_result or not topic_result.get("succeeded"):
            print(f"  [FAIL] 话题创建失败（文章已建）: {json.dumps(topic_result, ensure_ascii=False)[:300]}")
            return {"succeeded": True, "article_id": article_id, "article_url": article_url, "topic_fail": True}

        topic_data = ((topic_result.get("resp_data") or {}).get("topic") or {})
        print(f"  [OK] 话题已发布 topic_id={topic_data.get('topic_id')}")

        return {
            "succeeded": True,
            "article_id": article_id,
            "article_url": article_url,
            "topic_id": topic_data.get("topic_id"),
            "process_status": topic_data.get("process_status"),
        }

    def _process_md_images(self, md_content: str, base_dir: Path) -> Tuple[str, List[int]]:
        """处理 Markdown 中的图片引用，上传到 CDN 并替换 URL"""
        image_ids: List[int] = []
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
        for m in pattern.finditer(md_content):
            url = m.group(2)
            if url.startswith(("http://", "https://")):
                continue  # 远程图片暂不处理
            img_path = base_dir / url if not Path(url).is_absolute() else Path(url)
            if not img_path.exists():
                continue
            try:
                up = upload_image(img_path)
                image_ids.append(up["image_id"])
                md_content = md_content.replace(url, up.get("url", url), 1)
            except Exception as e:
                print(f"    [WARN] 图片上传失败({img_path}): {e}")
        return md_content, image_ids

    def _get_default_group_id(self) -> str:
        """从 zsxq-cli group +list --json 读取默认 group_id"""
        try:
            out = _sh(["zsxq-cli", "group", "+list", "--json"])
            data = json.loads(out)
            groups = data.get("groups", [])
            if groups:
                return str(groups[0].get("group_id", ""))
        except Exception:
            pass
        return ""