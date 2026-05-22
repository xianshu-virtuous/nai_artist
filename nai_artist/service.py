"""nai_artist Service：调用生图 API。

支持四种 API 协议模式：
- gateway:      NovelAI Gateway OpenAI 兼容接口（正向 user / 负向 system Negative prompt:）
- newapi:       BestNAI/NewAPI 中转，兼容新平台 OpenAI-chat 接口：
                  · 内层绘图参数 JSON（含 model / scale / sampler / seed / image_format）
                    序列化后放入 messages[0].content
                  · 请求体顶层携带 max_tokens（1 Anlas = 10000 tokens）
                  · 响应从 choices[0].message.content 提取 Markdown data URI 图片
- openai_image: 标准 OpenAI Images API（POST /v1/images/generations）
- raw_nai:      直连 NovelAI 官方 API（POST /ai/generate-image）

通过 config.api.api_mode 切换。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import zipfile
from typing import TYPE_CHECKING, Any, Literal

import httpx

from src.app.plugin_system.base import BaseService
from src.kernel.logger import get_logger

if TYPE_CHECKING:
    from .config import NaiArtistConfig

logger = get_logger("nai_artist")

# 匹配 NewAPI 返回的 data URI 图片
_DATA_URI_PATTERN = re.compile(r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)")

# 匹配返回的图片 URL（markdown 格式或裸 URL）
_IMAGE_URL_PATTERN = re.compile(
    r"https?://[^\s\)\]\"'>]+\.(?:png|jpg|jpeg|webp|gif)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 公共工具函数
# ---------------------------------------------------------------------------

def _normalize_tag_list(raw_tags: str) -> list[str]:
    """将逗号分隔的 tag 字符串清洗为有序去重列表。

    支持全角逗号，保留原有顺序，并按不区分大小写去重。
    """
    normalized = raw_tags.replace("\uff0c", ",").replace("\u3001", ",")
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

    - photo:   style tags -> base tags -> 翻译结果
    - drawing: style tags -> 翻译结果

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


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class NaiArtistService(BaseService):
    """NAI 生图核心 Service。

    负责组合提示词、发起 HTTP 请求、解析结果、管理本地缓存。
    通过 config.api.api_mode 自动选择 API 协议。
    """

    service_name: str = "nai_artist"
    service_description: str = "通过多种 API 协议生成 NAI 图片"
    version: str = "1.0.0"

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

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
        full_prompt = build_final_prompt(
            prompt_tags=prompt_tags,
            style_type=style_type,
            config=config,
        )

        api_mode = config.api.api_mode.strip().lower()

        if api_mode == "newapi":
            b64 = await self._via_newapi(full_prompt, preset, config)
        elif api_mode == "openai_image":
            b64 = await self._via_openai_image(full_prompt, preset, config)
        elif api_mode == "raw_nai":
            b64 = await self._via_raw_nai(full_prompt, preset, config)
        else:
            # 默认走 gateway
            b64 = await self._via_gateway(full_prompt, preset, config)

        if b64 is None:
            return None

        image_bytes = base64.b64decode(b64)
        self._save_cache(image_bytes, "png", config)
        logger.debug(f"NAI 生图成功，模式={api_mode}，大小={len(image_bytes)}字节")
        return b64

    # ------------------------------------------------------------------
    # 协议实现：gateway（NovelAI Gateway OpenAI 兼容接口）
    # ------------------------------------------------------------------

    async def _via_gateway(
        self,
        full_prompt: str,
        preset: Any,
        config: "NaiArtistConfig",
    ) -> str | None:
        """NovelAI Gateway OpenAI 兼容接口。

        正向提示词放 user message，负向提示词放 system message（Negative prompt: 前缀），
        scale/cfg_rescale/width/height 作为请求体顶层字段。
        """
        messages: list[dict[str, str]] = [
            {"role": "user", "content": full_prompt},
        ]

        # 负向提示词：放进 system message，以 "Negative prompt:" 开头
        neg = config.character.negative_tags.strip()
        if neg:
            messages.append({
                "role": "system",
                "content": f"Negative prompt: {neg}",
            })

        payload: dict[str, Any] = {
            "model": config.api.model,
            "messages": messages,
            "scale": config.nai_params.scale,
            "cfg_rescale": config.nai_params.cfg_rescale,
            "width": preset.width,
            "height": preset.height,
        }

        url = f"{config.api.base_url.rstrip('/')}/chat/completions"

        body = await self._post_json(url, payload, config)
        if body is None:
            return None

        try:
            content: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.warning(f"gateway 响应解析失败: {e}")
            return None

        # gateway 返回 markdown 图片链接：![image](http://host/images/uuid.png)
        return await self._extract_image_b64(content, config)

    # ------------------------------------------------------------------
    # 协议实现：newapi（BestNAI / NewAPI 中转）
    # ------------------------------------------------------------------

    async def _via_newapi(
        self,
        full_prompt: str,
        preset: Any,
        config: "NaiArtistConfig",
    ) -> str | None:
        """BestNAI/NewAPI 中转协议（兼容新平台 OpenAI-chat 接口）。

        将 NAI 绘图参数序列化为 JSON 字符串，放入 chat completions 的
        messages[0].content 中发送。响应可能是 data URI（base64 内嵌，
        格式为 Markdown 图片 ![image_0](data:image/...;base64,...)）或
        图片 URL，两种都兼容。

        新平台协议要点：
        - 内层 JSON 必须包含 model 字段（与外层一致）
        - scale / sampler / seed 等进阶参数从 nai_params 配置读取
        - 请求体顶层需携带 max_tokens（换算关系：1 Anlas = 10000 tokens）
        - 不要调用 /v1/images/generations，始终走 /v1/chat/completions
        """
        nai = config.nai_params

        # 构建内层绘图参数，按文档规范填写
        inner_params: dict[str, Any] = {
            "model": config.api.model,
            "prompt": full_prompt,
            "negative_prompt": config.character.negative_tags,
            "size": [preset.width, preset.height],
            "steps": preset.steps,
            "scale": nai.scale,
            "sampler": nai.sampler,
            "n_samples": 1,
            "image_format": config.api.image_format,
        }
        # seed 为 0 时表示随机，按文档省略该字段（留空即随机）
        if nai.seed != 0:
            inner_params["seed"] = nai.seed

        payload: dict[str, Any] = {
            "model": config.api.model,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(inner_params, ensure_ascii=False),
                }
            ],
            "stream": False,
            "max_tokens": config.api.max_tokens,
        }
        url = f"{config.api.base_url.rstrip('/')}/chat/completions"

        body = await self._post_json(url, payload, config)
        if body is None:
            return None

        try:
            content: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.warning(f"newapi 响应解析失败: {e}")
            return None

        return await self._extract_image_b64(content, config)

    # ------------------------------------------------------------------
    # 协议实现：openai_image（标准 OpenAI Images API）
    # ------------------------------------------------------------------

    async def _via_openai_image(
        self,
        full_prompt: str,
        preset: Any,
        config: "NaiArtistConfig",
    ) -> str | None:
        """标准 OpenAI Images API：POST /v1/images/generations。"""
        payload = {
            "model": config.api.model,
            "prompt": full_prompt,
            "n": 1,
            "size": f"{preset.width}x{preset.height}",
            "response_format": "b64_json",
        }
        url = f"{config.api.base_url.rstrip('/')}/images/generations"

        body = await self._post_json(url, payload, config)
        if body is None:
            return None

        try:
            return body["data"][0]["b64_json"]
        except (KeyError, IndexError) as e:
            logger.warning(f"openai_image 响应解析失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 协议实现：raw_nai（直连 NovelAI 官方 API）
    # ------------------------------------------------------------------

    async def _via_raw_nai(
        self,
        full_prompt: str,
        preset: Any,
        config: "NaiArtistConfig",
    ) -> str | None:
        """直连 NovelAI 官方 API：POST /ai/generate-image。

        NAI 官方返回 zip 压缩包，内含一张 png。
        """
        nai = config.nai_params
        payload = {
            "input": full_prompt,
            "model": config.api.model,
            "action": "generate",
            "parameters": {
                "width": preset.width,
                "height": preset.height,
                "steps": preset.steps,
                "negative_prompt": config.character.negative_tags,
                "seed": nai.seed,
                "sampler": nai.sampler,
                "scale": nai.scale,
                "cfg_rescale": nai.cfg_rescale,
                "noise_schedule": nai.noise_schedule,
                "uncond_scale": nai.uncond_scale,
                "n_samples": 1,
            },
        }
        url = f"{config.api.base_url.rstrip('/')}/ai/generate-image"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api.api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=config.api.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f"raw_nai HTTP 错误: {e.response.status_code}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"raw_nai 请求失败: {e}")
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = zf.namelist()[0]
                image_bytes = zf.read(name)
            return base64.b64encode(image_bytes).decode()
        except Exception as e:
            logger.warning(f"raw_nai 响应解压失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 响应图片提取（data URI / 图片 URL 通用）
    # ------------------------------------------------------------------

    async def _extract_image_b64(
        self,
        content: str,
        config: "NaiArtistConfig",
    ) -> str | None:
        """从响应 content 中提取图片，返回 base64 字符串。

        优先匹配 data URI（base64 内嵌），回退匹配图片 URL 并下载。
        """
        # 优先匹配 data URI
        match = _DATA_URI_PATTERN.search(content)
        if match:
            return match.group(2)

        # 回退：匹配图片 URL 并下载
        url_match = _IMAGE_URL_PATTERN.search(content)
        if url_match:
            image_url = url_match.group(0)
            logger.debug(f"响应返回了图片 URL，正在下载: {image_url}")
            return await self._download_image_as_b64(image_url, config)

        logger.warning(f"响应中未找到图片, content前200: {content[:200]}")
        return None

    # ------------------------------------------------------------------
    # 通用 HTTP 辅助
    # ------------------------------------------------------------------

    async def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        config: "NaiArtistConfig",
    ) -> dict[str, Any] | None:
        """通用 JSON POST 请求辅助方法。"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api.api_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=config.api.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"HTTP 错误: {e.response.status_code} — {e.response.text[:200]}"
            )
            return None
        except httpx.RequestError as e:
            logger.warning(f"请求失败: {e}")
            return None
        except ValueError as e:
            logger.warning(f"JSON 解析失败: {e}")
            return None

    async def _download_image_as_b64(
        self,
        image_url: str,
        config: "NaiArtistConfig",
    ) -> str | None:
        """下载图片 URL 并返回 base64 字符串。"""
        try:
            async with httpx.AsyncClient(timeout=config.api.timeout) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                return base64.b64encode(resp.content).decode()
        except httpx.HTTPStatusError as e:
            logger.warning(f"图片下载 HTTP 错误: {e.response.status_code} — {image_url}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"图片下载失败: {e} — {image_url}")
            return None

    # ------------------------------------------------------------------
    # 本地缓存
    # ------------------------------------------------------------------

    def _save_cache(
        self,
        image_bytes: bytes,
        fmt: str,
        config: "NaiArtistConfig",
    ) -> None:
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
