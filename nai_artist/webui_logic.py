"""nai_artist 独立 WebUI 的后端编排逻辑。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, TypedDict, cast

from src.core.config import init_core_config, init_model_config
from src.kernel.config.core import _render_toml_with_signature

from .action import get_style_hint
from .config import NaiArtistConfig
from .prompt_builder import translate_to_nai_tags
from .service import NaiArtistService, build_final_prompt


DEFAULT_PLUGIN_CONFIG_PATH = Path("config/plugins/nai_artist/config.toml")
DEFAULT_CORE_CONFIG_PATH = Path("config/core.toml")
DEFAULT_MODEL_CONFIG_PATH = Path("config/model.toml")


class ConfigOverrideData(TypedDict, total=False):
    """WebUI 允许编辑的配置覆盖字段。"""

    base_tags: str
    negative_tags: str
    photo_style_tags: str
    photo_width: int
    photo_height: int
    photo_steps: int
    drawing_style_tags: str
    drawing_width: int
    drawing_height: int
    drawing_steps: int


def initialize_webui_runtime(
    core_config_path: str | Path = DEFAULT_CORE_CONFIG_PATH,
    model_config_path: str | Path = DEFAULT_MODEL_CONFIG_PATH,
) -> None:
    """初始化独立 WebUI 所需的最小配置运行时。"""
    init_core_config(str(core_config_path))
    init_model_config(str(model_config_path))


def load_nai_artist_config(config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH) -> NaiArtistConfig:
    """加载当前 nai_artist 配置。"""
    return NaiArtistConfig.load(Path(config_path), auto_update=True)


def apply_config_overrides(config: NaiArtistConfig, overrides: ConfigOverrideData | None) -> NaiArtistConfig:
    """将白名单字段覆盖到配置实例。"""
    if not overrides:
        return config

    if "base_tags" in overrides:
        config.character.base_tags = overrides["base_tags"]
    if "negative_tags" in overrides:
        config.character.negative_tags = overrides["negative_tags"]

    if "photo_style_tags" in overrides:
        config.photo.style_tags = overrides["photo_style_tags"]
    if "photo_width" in overrides:
        config.photo.width = int(overrides["photo_width"])
    if "photo_height" in overrides:
        config.photo.height = int(overrides["photo_height"])
    if "photo_steps" in overrides:
        config.photo.steps = int(overrides["photo_steps"])

    if "drawing_style_tags" in overrides:
        config.drawing.style_tags = overrides["drawing_style_tags"]
    if "drawing_width" in overrides:
        config.drawing.width = int(overrides["drawing_width"])
    if "drawing_height" in overrides:
        config.drawing.height = int(overrides["drawing_height"])
    if "drawing_steps" in overrides:
        config.drawing.steps = int(overrides["drawing_steps"])

    return config


def config_to_editor_payload(config: NaiArtistConfig, config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH) -> dict[str, Any]:
    """将配置实例转换为前端编辑所需字段。"""
    return {
        "configPath": str(Path(config_path)),
        "plugin": {"enabled": config.plugin.enabled},
        "api": {
            "model": config.api.model,
            "translateModel": config.api.translate_model,
        },
        "character": {
            "baseTags": config.character.base_tags,
            "negativeTags": config.character.negative_tags,
        },
        "photo": {
            "styleTags": config.photo.style_tags,
            "width": config.photo.width,
            "height": config.photo.height,
            "steps": config.photo.steps,
        },
        "drawing": {
            "styleTags": config.drawing.style_tags,
            "width": config.drawing.width,
            "height": config.drawing.height,
            "steps": config.drawing.steps,
        },
    }


def save_nai_artist_config(
    overrides: ConfigOverrideData,
    config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH,
) -> NaiArtistConfig:
    """按白名单字段保存配置到 TOML。"""
    path = Path(config_path)
    config = load_nai_artist_config(path)
    apply_config_overrides(config, overrides)
    rendered = _render_toml_with_signature(NaiArtistConfig, config.model_dump(mode="python"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return config


def _make_service(config: NaiArtistConfig) -> NaiArtistService:
    plugin = SimpleNamespace(config=config)
    return NaiArtistService(plugin=cast(Any, plugin))


async def preview_translation(
    *,
    description: str,
    mode: Literal["photo", "drawing"],
    overrides: ConfigOverrideData | None = None,
    config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH,
) -> dict[str, Any]:
    """仅翻译并返回最终 prompt，不调用生图。"""
    config = apply_config_overrides(load_nai_artist_config(config_path), overrides)
    translated_tags = await translate_to_nai_tags(
        description,
        get_style_hint(mode),
        config.api.translate_model,
    )
    final_prompt = build_final_prompt(translated_tags, mode, config)
    return {
        "mode": mode,
        "translatedTags": translated_tags,
        "finalPrompt": final_prompt,
        "config": config_to_editor_payload(config, config_path),
    }


async def generate_preview(
    *,
    description: str,
    mode: Literal["photo", "drawing"],
    overrides: ConfigOverrideData | None = None,
    config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH,
) -> dict[str, Any]:
    """翻译并出图，返回最终 prompt 和 data URI。"""
    config = apply_config_overrides(load_nai_artist_config(config_path), overrides)
    translated_tags = await translate_to_nai_tags(
        description,
        get_style_hint(mode),
        config.api.translate_model,
    )
    final_prompt = build_final_prompt(translated_tags, mode, config)
    image_b64 = await _make_service(config).generate_image(
        prompt_tags=translated_tags,
        style_type=mode,
        config=config,
    )
    return {
        "mode": mode,
        "translatedTags": translated_tags,
        "finalPrompt": final_prompt,
        "imageDataUrl": f"data:image/png;base64,{image_b64}" if image_b64 else None,
        "config": config_to_editor_payload(config, config_path),
    }