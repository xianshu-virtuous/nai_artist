"""nai_artist 插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class NaiArtistConfig(BaseConfig):
    """nai_artist 插件配置类。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "NAI Artist 生图插件配置"

    @config_section("plugin")
    class PluginSection(SectionBase):
        """插件全局开关。"""

        enabled: bool = Field(
            default=True,
            description="是否启用 share_visual 生图功能；关闭后 Action 不会被 LLM 调用，system reminder 也不会注入",
        )

    @config_section("api")
    class ApiSection(SectionBase):
        """API 服务连接配置。"""

        api_mode: str = Field(
            default="gateway",
            description=(
                "API 协议模式。"
                "gateway = NovelAI Gateway OpenAI 兼容接口（正向提示词放 user，负向放 system Negative prompt:）；"
                "newapi = BestNAI/NewAPI 中转（把 NAI 参数 JSON 塞进 chat completions messages）；"
                "openai_image = 标准 OpenAI Images API（POST /v1/images/generations）；"
                "raw_nai = 直连 NovelAI 官方 API（POST /ai/generate-image）"
            ),
        )
        base_url: str = Field(
            default="http://localhost:3000/v1",
            description="API 服务地址，末尾不含斜杠",
        )
        api_key: str = Field(default="", description="API 访问令牌")
        model: str = Field(
            default="nai-diffusion-4-5-full",
            description="要调用的模型名称",
        )
        timeout: float = Field(default=120.0, description="HTTP 请求超时时间（秒）")
        translate_model: str = Field(
            default="",
            description=(
                "用于将自然语言翻译为 NAI tags 的模型名称"
                "（对应 config/model.toml 中 models 列表里的 name）。"
                "留空时回退到 UTILS_SMALL 任务模型。"
            ),
        )
        max_tokens: int = Field(
            default=100000,
            description=(
                "newapi 模式专用：外层 max_tokens 字段，"
                "控制本次请求允许消耗的最大预算。换算关系：1 Anlas = 10000 tokens。"
                "常用值：10000(1 Anlas)、50000(5 Anlas)、100000(10 Anlas)。"
            ),
        )
        image_format: str = Field(
            default="png",
            description=(
                "newapi 模式专用：返回图片格式，可选 \"png\" 或 \"webp\"。"
                "其他协议模式下忽略此字段。"
            ),
        )

    @config_section("character")
    class CharacterSection(SectionBase):
        """角色默认外貌 tags。"""

        base_tags: str = Field(
            default="1girl",
            description=(
                "正向 tags，描述 bot 默认外貌（逗号分隔的 booru-style 英文 tags）。"
                "仅 photo 模式会自动拼入；drawing 模式不自动绑定。"
            ),
        )
        negative_tags: str = Field(
            default=(
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "normal quality, jpeg artifacts, signature, watermark, username, blurry"
            ),
            description="负向 tags，排除不想要的画面",
        )

    @config_section("photo")
    class PhotoSection(SectionBase):
        """photo 模式风格预设参数。"""

        style_tags: str = Field(
            default=(
                "masterpiece, best quality, anime coloring, anime illustration, "
                "soft shading, clean lineart, detailed face, detailed eyes, "
                "natural blush, candid shot, photo composition"
            ),
            description=(
                "photo 模式附加风格 tags（与 character.base_tags 和翻译结果拼接），"
                "整体倾向于照片感的人像或场景图，而不是固定自拍构图"
            ),
        )
        width: int = Field(default=832, description="图片宽度（像素，仅允许 832/1024/1216）")
        height: int = Field(default=1216, description="图片高度（像素，仅允许 832/1024/1216）")
        steps: int = Field(default=28, description="采样步数（gateway 模式固定 28，其他模式免费限制 ≤28）")

    @config_section("drawing")
    class DrawingSection(SectionBase):
        """手绘画作风格预设参数。"""

        style_tags: str = Field(
            default=(
                "hand-drawn, sketch, rough lineart, visible brush strokes, "
                "colored pencil, watercolor texture, paper texture, "
                "sketchbook drawing, doodle, illustration"
            ),
            description="画作风格 tags（与 character.base_tags 和翻译结果拼接）",
        )
        width: int = Field(default=832, description="图片宽度（像素，仅允许 832/1024/1216）")
        height: int = Field(default=1216, description="图片高度（像素，仅允许 832/1024/1216）")
        steps: int = Field(default=28, description="采样步数（gateway 模式固定 28，其他模式免费限制 ≤28）")

    @config_section("nai_params")
    class NaiParamsSection(SectionBase):
        """NAI 采样参数。

        gateway 模式下仅 scale 和 cfg_rescale 生效（步数固定 28，采样器不可选）。
        newapi/raw_nai 模式下全部参数生效（scale、sampler、seed 均会传给新平台）。
        """

        scale: float = Field(
            default=5.0,
            description="提示词指导强度（Prompt Guidance）。gateway 模式范围 1.0-10.0，默认 5.0",
        )
        cfg_rescale: float = Field(
            default=0.0,
            description="CFG rescale，缓解高 CFG 下色彩过饱和。gateway 模式范围 0.0-1.0，默认 0.0",
        )
        sampler: str = Field(
            default="k_euler_ancestral",
            description=(
                "采样器名称（gateway 模式下忽略）。"
                "常用值：k_euler, k_euler_ancestral, k_dpmpp_2s_ancestral, "
                "k_dpmpp_2m_sde, k_dpmpp_sde, ddim"
            ),
        )
        noise_schedule: str = Field(
            default="native",
            description="噪声调度方式（gateway 模式下忽略）。常用值：native, karras, exponential, polyexponential",
        )
        uncond_scale: float = Field(
            default=1.0,
            description="负向提示词强度缩放（gateway 模式下忽略）。1.0 表示正常强度",
        )
        seed: int = Field(
            default=0,
            description="随机种子。0 表示随机",
        )

    @config_section("storage")
    class StorageSection(SectionBase):
        """本地缓存配置。"""

        cache_dir: str = Field(
            default="data/media_cache/images/nai_artist",
            description="生成图片的本地缓存目录",
        )
        max_cache: int = Field(
            default=100,
            description="最多缓存的图片数量，超出时自动删除最旧的文件",
        )

    @config_section("webui")
    class WebUISection(SectionBase):
        """独立 WebUI 的监听地址配置。"""

        host: str = Field(
            default="127.0.0.1",
            description=(
                "WebUI 监听地址。127.0.0.1 仅本机可访问；"
                "0.0.0.0 表示监听所有网卡，可被局域网其他设备访问。"
            ),
        )
        port: int = Field(
            default=8011,
            description="WebUI 监听端口。若端口冲突，可改成其他未占用端口。",
        )

    plugin: PluginSection = Field(default_factory=PluginSection)
    api: ApiSection = Field(default_factory=ApiSection)
    character: CharacterSection = Field(default_factory=CharacterSection)
    photo: PhotoSection = Field(default_factory=PhotoSection)
    drawing: DrawingSection = Field(default_factory=DrawingSection)
    nai_params: NaiParamsSection = Field(default_factory=NaiParamsSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    webui: WebUISection = Field(default_factory=WebUISection)
