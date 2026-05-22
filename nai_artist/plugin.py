"""nai_artist 插件入口。

加载后注册 system reminder 到 actor bucket，让 bot 获得手机拍照和画画的人设。
"""

from __future__ import annotations

import os

from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.logger import get_logger

from .action import ShareVisualAction
from .config import NaiArtistConfig
from .service import NaiArtistService

logger = get_logger("nai_artist")

_REMINDER_BUCKET = "actor"
_REMINDER_NAME = "关于拍照和画画"
_REMINDER_CONTENT = (
    "你有一个随身携带的手机，能够随时随地记录发给对方，"
    "同时你也会画画，心情好可以答应别人的请求画画。"
    "当对方要求你画其他角色、OC 或二创对象时，不要擅自脑补和补全未被明确说明的人设细节；"
    "只能根据对方已提供的信息来画，不够明确时就先问或保持泛化。"
)


@register_plugin
class NaiArtistPlugin(BasePlugin):
    """NAI Artist 插件。"""

    plugin_name: str = "nai_artist"
    plugin_description: str = "让 bot 像真人一样用手机拍照或展示手绘画作"
    plugin_version: str = "1.0.0"

    configs: list[type] = [NaiArtistConfig]
    dependent_components: list[str] = []

    def get_components(self) -> list[type]:
        """返回插件提供的组件类列表。"""
        return [NaiArtistService, ShareVisualAction]

    async def on_plugin_loaded(self) -> None:
        """插件加载时注册 system reminder 并确保缓存目录存在。"""
        from src.app.plugin_system.api import prompt_api

        if isinstance(self.config, NaiArtistConfig) and not self.config.plugin.enabled:
            logger.info("nai_artist 已通过配置禁用，跳过 reminder 注册")
            return

        prompt_api.add_system_reminder(
    bucket=_REMINDER_BUCKET,
    name=_REMINDER_NAME,
    content=_REMINDER_CONTENT,
)
        logger.debug("nai_artist actor reminder 已注册")

        if isinstance(self.config, NaiArtistConfig):
            cache_dir = self.config.storage.cache_dir
            os.makedirs(cache_dir, exist_ok=True)
            logger.debug(f"nai_artist 缓存目录已确认: {cache_dir}")

    async def on_plugin_unloaded(self) -> None:
        """插件卸载时移除 system reminder。"""
        from src.core.prompt import get_system_reminder_store

        prompt_api.remove_system_reminder(_REMINDER_BUCKET, _REMINDER_NAME)
        logger.debug("nai_artist actor reminder 已移除")
