"""nai_artist Service：调用 NewAPI 生成图片。

通过 OpenAI Chat Completions 兼容接口与 NewAPI/BestNAI 通信，
将 NAI 生图参数序列化为字符串传入 messages，解析返回的 base64 图片。
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import TYPE_CHECKING, Literal

import httpx

from src.core.components.base.service import BaseService
from src.kernel.logger import get_logger

if TYPE_CHECKING:
    from .config import NaiArtistConfig

logger = get_logger("nai_artist")

# 匹配 NewAPI 返回的 data URI 图片
_DATA_URI_PATTERN = re.compile(r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)")


def _normalize_tag_list(raw_tags: str) -> list[str]:
    """将逗号分隔的 tag 字符串清洗为有序去重列表。

    支持全角逗号，保留原有顺序，并按不区分大小写去重。
    """
    normalized = raw_tags.replace("，", ",").replace("、", ",")
    seen: set[str] = set()
    result: list[str] = []
    for part in normalized.split(","):
        tag = part.strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result


def _merge_prompt_tags(*tag_groups: str) -> str:
    """按顺序合并多组 tags，保留前者优先级并去重。"""
    merged: list[str] = []
    seen: set[str] = set()
    for group in tag_groups:
        for tag in _normalize_tag_list(group):
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(tag)
    return ", ".join(merged)


def build_final_prompt(
    prompt_tags: str,
    style_type: Literal["photo", "drawing"],
    config: "NaiArtistConfig",
) -> str:
    """构建最终发送给 NAI 的完整 prompt。

    - photo: style tags → base tags → 翻译结果
    - drawing: style tags → 翻译结果

    drawing 模式不再自动绑定 bot 的 base tags，避免当用户要求绘制其他角色时，
    角色固定外貌词干扰模型发挥。此时应由主模型在自然语言里明确描述要画的对象。
    """
    preset = config.photo if style_type == "photo" else config.drawing
    if style_type == "drawing":
        return _merge_prompt_tags(
            preset.style_tags,
            prompt_tags,
        )

    return _merge_prompt_tags(
        preset.style_tags,
        config.character.base_tags,
        prompt_tags,
    )


class NaiArtistService(BaseService):
    """NAI 生图核心 Service。

    负责组合提示词、发起 HTTP 请求、解析结果、管理本地缓存。
    """

    service_name: str = "nai_artist"
    service_description: str = "通过 NewAPI/BestNAI 生成 NAI 图片"
    version: str = "1.0.0"

    async def generate_image(
        self,
        prompt_tags: str,
        style_type: Literal["photo", "drawing"],
        config: "NaiArtistConfig",
    ) -> str | None:
        """生成一张图片并返回 base64 字符串。

        Args:
            prompt_tags: 翻译好的 NAI tags（自然语言翻译结果）
            style_type: 风格类型，"photo" 或 "drawing"
            config: 插件配置实例

        Returns:
            base64 编码的图片字符串；失败时返回 None
        """
        preset = config.photo if style_type == "photo" else config.drawing

        # photo 会拼入角色固定 tags；drawing 则仅保留风格串和描述翻译结果。
        full_prompt = build_final_prompt(
            prompt_tags=prompt_tags,
            style_type=style_type,
            config=config,
        )

        nai_params = {
            "prompt": full_prompt,
            "negative_prompt": config.character.negative_tags,
            "size": [preset.width, preset.height],
            "steps": preset.steps,
        }

        payload = {
            "model": config.api.model,
            "stream": False,
            "messages": [
                {"role": "user", "content": json.dumps(nai_params, ensure_ascii=False)}
            ],
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api.api_key}",
        }

        url = f"{config.api.base_url.rstrip('/')}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=config.api.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f"NAI 生图 HTTP 错误: {e.response.status_code} — {e.response.text[:200]}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"NAI 生图请求失败: {e}")
            return None

        try:
            body = resp.json()
            content: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"NAI 生图响应解析失败: {e} — body前200: {resp.text[:200]}")
            return None

        match = _DATA_URI_PATTERN.search(content)
        if not match:
            logger.warning(f"NAI 响应中未找到图片数据，content前200: {content[:200]}")
            return None

        fmt, b64_data = match.group(1), match.group(2)
        image_bytes = base64.b64decode(b64_data)

        self._save_cache(image_bytes, fmt, config)
        logger.debug(f"NAI 生图成功，格式={fmt}，大小={len(image_bytes)}字节")
        return b64_data

    def _save_cache(self, image_bytes: bytes, fmt: str, config: "NaiArtistConfig") -> None:
        """将图片保存到本地缓存，并按 max_cache 限制清理最旧的文件。

        Args:
            image_bytes: 图片二进制数据
            fmt: 图片格式（如 "png"）
            config: 插件配置实例
        """
        cache_dir = config.storage.cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        filename = f"{int(time.time() * 1000)}.{fmt}"
        filepath = os.path.join(cache_dir, filename)
        try:
            with open(filepath, "wb") as f:
                f.write(image_bytes)
        except OSError as e:
            logger.warning(f"NAI 缓存写入失败: {e}")
            return

        # 超出 max_cache 时删除最旧的文件
        max_cache = config.storage.max_cache
        if max_cache <= 0:
            return

        try:
            all_files = sorted(
                (
                    os.path.join(cache_dir, fn)
                    for fn in os.listdir(cache_dir)
                    if os.path.isfile(os.path.join(cache_dir, fn))
                ),
                key=os.path.getmtime,
            )
            while len(all_files) > max_cache:
                oldest = all_files.pop(0)
                try:
                    os.remove(oldest)
                    logger.debug(f"NAI 缓存清理: {oldest}")
                except OSError:
                    pass
        except OSError as e:
            logger.warning(f"NAI 缓存清理失败: {e}")
