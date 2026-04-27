#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识星球发布工具 - 发布模块

支持两种发布模式:
1. 话题发布（短内容）: POST /v2/groups/{group_id}/topics
2. 文章发布（长内容）: 先 POST /v2/articles 创建文章，再 POST topics 引用文章
"""

import json
import mimetypes
import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import requests

from config import ENDPOINTS, GROUP_ID, PUBLISH_HISTORY_FILE, QINIU_UPLOAD_URL
from auth import load_auth, build_request_headers
from markdown_converter import (
    markdown_to_article_html,
    markdown_to_topic_text,
    extract_title_from_markdown,
    format_hashtags,
)


class ZsxqPublisher:
    """知识星球内容发布器"""

    def __init__(self):
        self.cookies, self.base_headers = load_auth()
        self.history = self._load_history()

    def _get_upload_token(self) -> Optional[str]:
        """获取七牛云上传 token"""
        payload = {
            "req_data": {
                "type": "image",
                "usage": "article",
                "name": "",
                "hash": "",
                "size": "",
            }
        }
        result = self._post(ENDPOINTS["upload_image"], payload)
        if result and result.get("succeeded"):
            token = result.get("resp_data", {}).get("upload_token", "")
            if token:
                return token
        print(f"  [WARN] 获取上传 token 失败")
        return None

    def _upload_image(self, image_data: bytes, filename: str) -> Optional[Dict]:
        """上传单张图片到知识星球（七牛云）

        Returns:
            {"image_id": 123, "url": "https://..."} 或 None
        """
        token = self._get_upload_token()
        if not token:
            return None

        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            files = {"file": (filename, image_data, mime_type)}
            data = {"token": token}
            resp = requests.post(
                QINIU_UPLOAD_URL,
                files=files,
                data=data,
                timeout=60,
            )
            if resp.status_code == 200:
                body = resp.json()
                if body.get("succeeded"):
                    image_id = body.get("resp_data", {}).get("image_id")
                    url = body.get("link", "")
                    return {"image_id": image_id, "url": url}
                else:
                    print(f"  [WARN] 七牛云上传返回失败: {body}")
            else:
                print(f"  [WARN] 七牛云上传 HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.exceptions.Timeout:
            print("  [WARN] 七牛云上传超时")
        except requests.exceptions.ConnectionError:
            print("  [WARN] 七牛云上传网络连接失败")
        except Exception as e:
            print(f"  [WARN] 七牛云上传异常: {e}")
        return None

    def _process_article_images(
        self, md_content: str, base_dir: Optional[Path] = None
    ) -> Tuple[str, List[int]]:
        """处理 Markdown 中的图片引用：上传到知识星球并替换 URL

        Returns:
            (更新后的 markdown, image_ids 列表)
        """
        image_ids = []

        # 匹配 Markdown 图片语法: ![alt](url)
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
        matches = list(pattern.finditer(md_content))
        if not matches:
            return md_content, image_ids

        print(f"  检测到 {len(matches)} 张图片")

        for i, match in enumerate(matches):
            alt_text = match.group(1)
            url = match.group(2)
            print(f"  [{i+1}/{len(matches)}] 处理图片: {alt_text or url}")

            image_data = None
            filename = url.rsplit("/", 1)[-1] if "/" in url else url
            # 去除 URL 参数
            if "?" in filename:
                filename = filename.split("?")[0]
            if not filename:
                filename = f"image_{i+1}"

            # 本地图片
            if not url.startswith(("http://", "https://")):
                img_path = Path(url)
                if not img_path.is_absolute():
                    if base_dir:
                        img_path = base_dir / url
                    else:
                        img_path = Path(url).resolve()
                if img_path.exists():
                    image_data = img_path.read_bytes()
                    if not filename or "." not in filename:
                        filename = img_path.name
                else:
                    print(f"    [SKIP] 文件不存在: {img_path}")
                    continue
            else:
                # 远程图片：下载后上传
                try:
                    print(f"    下载远程图片...")
                    resp = requests.get(url, timeout=30)
                    if resp.status_code == 200:
                        image_data = resp.content
                    else:
                        print(f"    [SKIP] 下载失败 HTTP {resp.status_code}")
                        continue
                except Exception as e:
                    print(f"    [SKIP] 下载异常: {e}")
                    continue

            if not image_data:
                print(f"    [SKIP] 无法获取图片数据")
                continue

            result = self._upload_image(image_data, filename)
            if result and result.get("image_id"):
                image_ids.append(result["image_id"])
                cdn_url = result.get("url", "")
                if cdn_url:
                    escaped_url = re.escape(url)
                    md_content = re.sub(escaped_url, cdn_url, md_content, count=1)
                    print(f"    [OK] image_id={result['image_id']}")
            else:
                print(f"    [FAIL] 上传失败，保留原始引用")

        return md_content, image_ids

    def publish_topic(
        self, text: str, title: str = "", tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """发布话题（短内容）

        Args:
            text: 话题正文
            title: 可选标题（会加粗显示）
            tags: 可选标签列表
        Returns:
            API 响应数据
        """
        # 构建话题文本
        topic_text = markdown_to_topic_text(text, title=title)

        # 添加标签
        if tags:
            topic_text += "\n" + format_hashtags(tags)

        # 构建请求体
        payload = {"req_data": {"type": "talk", "text": topic_text}}

        # 发送请求
        result = self._post(ENDPOINTS["create_topic"], payload)

        if result and result.get("succeeded"):
            topic_data = result.get("resp_data", {}).get("topic", {})
            self._record_history(
                publish_type="topic",
                title=title or text[:50],
                topic_id=topic_data.get("topic_id"),
                status=topic_data.get("process_status", "unknown"),
            )
            print(f"  [OK] 话题发布成功!")
            print(f"  话题ID: {topic_data.get('topic_id')}")
            print(f"  状态: {topic_data.get('process_status', 'unknown')}")
        else:
            print(f"  [FAIL] 话题发布失败")
            if result:
                print(f"  响应: {json.dumps(result, ensure_ascii=False)}")

        return result or {}

    def publish_article(
        self, md_content: str, title: str = "", tags: Optional[List[str]] = None,
        base_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """发布文章（长内容，两步流程）

        Step 0: 处理图片 → 上传到知识星球获取 image_ids
        Step 1: POST /v2/articles 创建文章 → 获取 article_id
        Step 2: POST /v2/groups/{id}/topics 创建引用文章的话题

        Args:
            md_content: Markdown 格式的文章内容
            title: 文章标题（如果为空，从 Markdown 中提取）
            tags: 可选标签列表
            base_dir: 本地图片引用的基准目录
        Returns:
            API 响应数据
        """
        # 提取标题和正文
        if not title:
            title, body = extract_title_from_markdown(md_content)
        else:
            _, body = extract_title_from_markdown(md_content)

        if not title:
            title = "未命名文章"

        # Step 0: 处理图片上传
        print(f"  Step 0: 处理图片...")
        md_content, image_ids = self._process_article_images(md_content, base_dir=base_dir)
        print(f"  图片处理完成，共 {len(image_ids)} 张")

        # Step 1: 创建文章
        print(f"  Step 1: 创建文章 '{title}'...")
        article_html = markdown_to_article_html(md_content)

        article_payload = {
            "req_data": {
                # Current /v2/articles API requires explicit group_id; otherwise it returns code 1033.
                "group_id": GROUP_ID,
                "title": title,
                "content": article_html,
                # Keep the original Markdown for compatibility with the current editor / viewer.
                "original_content": md_content,
                "image_ids": image_ids,
            }
        }

        article_result = None
        for attempt in range(1, 6):
            article_result = self._post(ENDPOINTS["create_article"], article_payload)
            if article_result and article_result.get("succeeded"):
                break

            code = article_result.get("code") if isinstance(article_result, dict) else None
            if code in (429, 1059) or article_result is None:
                print(f"    创建文章瞬时失败 (code={code})，第 {attempt} 次重试...")
                time.sleep(min(12.0, 2.5 * attempt))
                continue
            break

        if not article_result or not article_result.get("succeeded"):
            print(f"  [FAIL] 文章创建失败")
            if article_result:
                print(f"  响应: {json.dumps(article_result, ensure_ascii=False)}")
            return article_result or {}

        article_id = article_result["resp_data"]["article_id"]
        article_url = article_result["resp_data"]["article_url"]
        print(f"  [OK] 文章已创建: {article_id}")
        print(f"  文章链接: {article_url}")

        # 适当延迟，避免请求过快
        time.sleep(random.uniform(0.5, 1.5))

        # Step 2: 创建话题引用文章
        print(f"  Step 2: 创建话题引用文章...")

        # 构建话题文本（摘要 + 标签）
        summary = body[:200] if body else ""
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
            topic_result = self._post(ENDPOINTS["create_topic"], topic_payload)
            if topic_result and topic_result.get("succeeded"):
                break

            code = topic_result.get("code") if isinstance(topic_result, dict) else None
            # Common transient failures observed from the web API.
            if code in (429, 1059) or topic_result is None:
                time.sleep(min(12.0, 2.5 * attempt))
                continue
            break

        if topic_result and topic_result.get("succeeded"):
            topic_data = topic_result.get("resp_data", {}).get("topic", {})
            self._record_history(
                publish_type="article",
                title=title,
                topic_id=topic_data.get("topic_id"),
                article_id=article_id,
                article_url=article_url,
                status=topic_data.get("process_status", "unknown"),
            )
            print(f"  [OK] 文章发布成功!")
            print(f"  话题ID: {topic_data.get('topic_id')}")
            print(f"  文章ID: {article_id}")
            print(f"  文章链接: {article_url}")
            print(f"  状态: {topic_data.get('process_status', 'unknown')}")
            return topic_result
        else:
            print(f"  [WARN] 文章已创建但话题关联失败")
            if topic_result:
                code = topic_result.get("code", "?")
                print(f"  错误码: {code}")
                print(f"  响应: {json.dumps(topic_result, ensure_ascii=False)}")
            print(f"  文章ID: {article_id} (可手动关联)")
            self._record_history(
                publish_type="article",
                title=title,
                article_id=article_id,
                article_url=article_url,
                status="topic_failed",
            )
            # 返回话题创建失败的结果，让调用方能感知到失败
            return topic_result if topic_result else {"succeeded": False, "code": "topic_creation_failed"}

    def publish_file(
        self, file_path: str, mode: str = "auto", tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """发布文件

        Args:
            file_path: Markdown 文件路径
            mode: 发布模式 - "auto" (自动判断), "topic" (话题), "article" (文章)
            tags: 可选标签列表
        """
        from config import ARTICLE_THRESHOLD

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        md_content = path.read_text(encoding="utf-8")
        title, _ = extract_title_from_markdown(md_content)

        print(f"发布文件: {path.name}")
        print(f"标题: {title}")
        print(f"字符数: {len(md_content)}")

        # 自动判断模式
        if mode == "auto":
            mode = "article" if len(md_content) > ARTICLE_THRESHOLD else "topic"
            print(f"自动选择模式: {mode}")

        if mode == "article":
            return self.publish_article(md_content, title=title, tags=tags, base_dir=path.parent)
        else:
            return self.publish_topic(md_content, title=title, tags=tags)

    def _post(self, url: str, payload: Dict) -> Optional[Dict]:
        """发送 POST 请求"""
        headers = build_request_headers(self.base_headers)

        try:
            resp = requests.post(
                url,
                headers=headers,
                cookies=self.cookies,
                json=payload,
                timeout=30,
            )

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                print("  [ERROR] Cookie 已过期，请运行 login 命令重新登录授权")
                return None
            else:
                print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:200]}")
                return None

        except requests.exceptions.Timeout:
            print("  [ERROR] 请求超时")
            return None
        except requests.exceptions.ConnectionError:
            print("  [ERROR] 网络连接失败")
            return None
        except Exception as e:
            print(f"  [ERROR] 请求异常: {e}")
            return None

    def _record_history(self, **kwargs):
        """记录发布历史"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "group_id": GROUP_ID,
            **kwargs,
        }
        self.history.append(record)
        self._save_history()

    def _load_history(self) -> list:
        """加载发布历史"""
        if PUBLISH_HISTORY_FILE.exists():
            try:
                with open(PUBLISH_HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception):
                return []
        return []

    def _save_history(self):
        """保存发布历史"""
        try:
            with open(PUBLISH_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [WARN] 保存发布历史失败: {e}")

    def get_history(self, count: int = 10) -> list:
        """获取最近的发布历史"""
        return self.history[-count:]
