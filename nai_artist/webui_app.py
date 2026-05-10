"""nai_artist 独立 WebUI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .webui_logic import (
    DEFAULT_PLUGIN_CONFIG_PATH,
    apply_config_overrides,
    config_to_editor_payload,
    generate_preview,
    initialize_webui_runtime,
    load_nai_artist_config,
    preview_translation,
    save_nai_artist_config,
)


class ConfigOverrides(BaseModel):
    base_tags: str | None = None
    negative_tags: str | None = None
    photo_style_tags: str | None = None
    photo_width: int | None = None
    photo_height: int | None = None
    photo_steps: int | None = None
    drawing_style_tags: str | None = None
    drawing_width: int | None = None
    drawing_height: int | None = None
    drawing_steps: int | None = None


class PreviewRequest(BaseModel):
    mode: Literal["photo", "drawing"]
    description: str = Field(min_length=1)
    overrides: ConfigOverrides | None = None


class SaveRequest(BaseModel):
    overrides: ConfigOverrides


def get_webui_bind_settings(
    config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH,
) -> tuple[str, int]:
    """从插件配置中读取 WebUI 监听地址。"""
    config = load_nai_artist_config(config_path)
    return config.webui.host, config.webui.port


def create_app(
    *,
    config_path: str | Path = DEFAULT_PLUGIN_CONFIG_PATH,
    initialize_runtime: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if initialize_runtime:
            initialize_webui_runtime()
        yield

    app = FastAPI(
        title="NAI Artist WebUI",
        description="独立的 nai_artist 提示词测试与出图工作台",
        lifespan=lifespan,
    )
    app.state.nai_artist_config_path = Path(config_path)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(Path(__file__).with_name("webui") / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "nai_artist_webui"}

    @app.get("/api/config")
    async def get_config() -> dict:
        config = load_nai_artist_config(app.state.nai_artist_config_path)
        return config_to_editor_payload(config, app.state.nai_artist_config_path)

    @app.post("/api/translate")
    async def api_translate(request: PreviewRequest) -> dict:
        return await preview_translation(
            description=request.description,
            mode=request.mode,
            overrides=request.overrides.model_dump(exclude_none=True) if request.overrides else None,
            config_path=app.state.nai_artist_config_path,
        )

    @app.post("/api/generate")
    async def api_generate(request: PreviewRequest) -> dict:
        result = await generate_preview(
            description=request.description,
            mode=request.mode,
            overrides=request.overrides.model_dump(exclude_none=True) if request.overrides else None,
            config_path=app.state.nai_artist_config_path,
        )
        if result["imageDataUrl"] is None:
            raise HTTPException(status_code=502, detail="图片生成失败")
        return result

    @app.post("/api/config/save")
    async def api_save_config(request: SaveRequest) -> dict:
        config = save_nai_artist_config(
            request.overrides.model_dump(exclude_none=True),
            app.state.nai_artist_config_path,
        )
        return config_to_editor_payload(config, app.state.nai_artist_config_path)

    @app.post("/api/config/preview")
    async def api_preview_config(request: SaveRequest) -> dict:
        config = load_nai_artist_config(app.state.nai_artist_config_path)
        apply_config_overrides(config, request.overrides.model_dump(exclude_none=True))
        return config_to_editor_payload(config, app.state.nai_artist_config_path)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    host, port = get_webui_bind_settings()

    uvicorn.run(
        "plugins.nai_artist.webui_app:app",
        host=host,
        port=port,
        reload=True,
    )