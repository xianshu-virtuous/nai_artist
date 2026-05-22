"""nai_artist Action：分享图片。

统一的生图 Action，提供手机拍照（photo）和手绘画作（drawing）两种模式。
LLM 根据对话情境自主选择模式并填写画面描述，插件负责翻译和生图。
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from src.app.plugin_system.api.send_api import send_image
from src.app.plugin_system.api.service_api import get_service
from src.core.components.base.action import BaseAction
from src.kernel.logger import get_logger

from src.app.plugin_system.api.send_api import send_image
from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BaseAction

logger = get_logger("nai_artist")

_STYLE_HINTS: dict[str, str] = {
    "photo": "photo composition, candid shot, natural pose, varied framing",
    "drawing": "hand-drawn composition, sketchbook layout, illustration framing",
}


def get_style_hint(mode: Literal["photo", "drawing"]) -> str:
    """获取模式对应的轻量 style hint。

    该提示只用于帮助翻译模型理解构图/用途，不应与 config 中的风格串竞争。
    """
    return _STYLE_HINTS.get(mode, "")


class ShareVisualAction(BaseAction):
    """分享图片 Action。

    让 bot 像真人一样用手机拍照或展示手绘画作。
    """

    action_name: str = "share_visual"
    action_description: str = (
        '''主动发图规则:
当你判断当前对话满足以下任一条件时，应主动生成图片（无需等用户再次要求）：

用户明确要求画图、生成图片、创作图像。

用户要求自拍、拍照、发照片、发图，或明显向你索要一张图（如“自拍一张”“发张照片”“拍给我看”）。

用户在延续绘图话题（如“再来一张”“换个姿势”“重新画”）。

对话重心已明显变成想看你的样子、穿搭、状态或某个视觉重点——此时发图比继续文字描述更自然。

发一张图片能够更好的推动对话氛围的时候，虽然对话走向没有提及画图，但你觉得发图会是更自然的回应。

不触发的情况：无关知识问答、纯技术讨论、只是提到“图片”但不是要求生成、普通暧昧聊天、口嗨、夸赞、试探或玩笑（未进入“想看看画面”的阶段）。
注意：非用户主动要求重画时，不要重复生成完全相同的内容。

图片类型选择（主动判断）

photo：二次元插画风格的照片感人像或场景图。会自动带入你自己的默认外貌（不固定为自拍）。

drawing：更明显的手绘画作风格。不会自动绑定你的默认外貌。若要画别人、OC、二创角色或非你自己的对象，需在 content 里明确描述。

主动生成时的约束

当用户要求画其他角色时，只能写入用户已经明确给出的信息。

不要擅自补全未说明的发色、服装、体型、年龄感、配饰、背景或人物关系。

如果用户给的信息不足，就只给出用户的信息即可，这是为了确保生成的内容与用户的期望一致，避免误导或错误的补全。

主动性示例

用户：“今天心情真好～” → 你主动生成一张阳光明媚、你微笑的 photo 图片。

用户：“给我画一个戴帽子的女孩，其他随便” → 你不补全发色/服装，用泛化描述（如“一个戴帽子的女孩”）生成 drawing。

用户连续两次说“再来一张” → 主动生成不同构图/姿势的新图片。

总之：在符合触发条件时，主动、自然、恰当地发图，同时严格遵守已经给出的角色设定与信息约束。'''
    )
    primary_action: bool = True

    async def go_activate(self) -> bool:
        """检查插件是否启用。"""
        config = self.plugin.config
        if isinstance(config, NaiArtistConfig) and not config.plugin.enabled:
            return False
        return True

    async def execute(
        self,
        mode: Annotated[Literal["photo", "drawing"], "photo=手机拍摄，drawing=手绘画作"],
        content: Annotated[
            str,
            "用自然语言描述画面内容——场景、人物、氛围、情感。若是在画其他角色，只能写用户已明确提供的设定，不要补完未说明的细节。",
        ],
    ) -> tuple[bool, str]:
        """执行生图并发送。

        Args:
            mode: 生图模式
            content: 自然语言画面描述

        Returns:
            (成功标志, 结果说明)
        """
        service = get_service("nai_artist:service:nai_artist")
        if service is None:
            logger.warning("nai_artist service 未加载")
            return False, "nai_artist service 未加载"

        service = cast(NaiArtistService, service)
        config = cast(NaiArtistConfig, self.plugin.config)

        # 翻译自然语言为 NAI tags
        style_hint = get_style_hint(mode)
        prompt_tags = await translate_to_nai_tags(content, style_hint, config.api.translate_model)

        # 生成图片
        b64_image = await service.generate_image(
            prompt_tags=prompt_tags,
            style_type=mode,
            config=config,
        )
        if b64_image is None:
            return False, "图片生成失败"

        # 发送图片
        ok = await send_image(
            image_data=b64_image,
            stream_id=self.chat_stream.stream_id,
            platform=self.chat_stream.platform,
        )
        if not ok:
            return False, "图片发送失败"

        return True, "已发送图片"
