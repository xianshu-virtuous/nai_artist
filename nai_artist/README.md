# nai_artist 插件

让 bot 像真人一样用手机拍照或展示手绘画作。LLM 在对话中自主判断时机，用自然语言描述画面 → 自动翻译为 NAI tags → 调用 NewAPI 生图 → 发送给对方。

---

## 快速上手

### 1. 确认 NewAPI 服务已运行

本插件通过 [NewAPI](https://github.com/Calcium-Ion/new-api) / OneAPI 中转与 BestNAI 通信，需要先部署好中转服务。

### 2. 修改配置

编辑 `config/plugins/nai_artist/config.toml`：

```toml
[api]
base_url = "http://你的服务器:3000/v1"   # NewAPI 服务地址
api_key  = "sk-xxxxxxxxxxxxxxxxxxxx"      # NewAPI 访问令牌
model    = "nai-diffusion-4-5-full-anlas-0"

[character]
# 填写角色固定外貌的 booru-style 英文 tags（逗号分隔）
# 建议包含：人数、发色、发型、眼色、常见服装等稳定特征
base_tags     = "1girl, silver hair, blue eyes, medium hair, white dress"
negative_tags = "lowres, bad anatomy, bad hands, text, watermark, blurry"
```

> `character.base_tags` 决定了角色的"长相"，每次生图都会自动拼入，越详细越稳定。

现在的行为是：

- `photo` 模式会自动拼入 `character.base_tags`
- `drawing` 模式**不会**自动拼入 `character.base_tags`
- 如果是画其他角色、OC、二创角色或非 bot 本人，请优先使用 `drawing`，并在 `content` 中明确描述对象

### 3. 启用插件

插件放置在 `plugins/nai_artist/` 目录下，框架会自动在启动时加载，无需额外操作。

---

## 配置项说明

| 节 | 字段 | 默认值 | 说明 |
|---|---|---|---|
| `[api]` | `base_url` | `http://localhost:3000/v1` | NewAPI 服务地址 |
| | `api_key` | `""` | NewAPI 访问令牌 |
| | `model` | `nai-diffusion-4-5-full-anlas-0` | NAI 模型名称 |
| | `timeout` | `120.0` | 请求超时（秒） |
| `[character]` | `base_tags` | `"1girl"` | bot 默认外貌 tags；仅 `photo` 模式自动拼入 |
| | `negative_tags` | （见默认值） | 负向 tags |
| `[photo]` | `style_tags` | `"masterpiece, best quality, anime coloring, anime illustration, ..."` | 二次元插画风格的照片感人像/场景图附加 tags |
| | `width` / `height` | `832 × 1216` | 图片分辨率 |
| | `steps` | `23` | 采样步数（免费 ≤28） |
| `[drawing]` | `style_tags` | `"hand-drawn, sketch, rough lineart, visible brush strokes, ..."` | 更强手绘感的画作附加 tags |
| | `width` / `height` | `832 × 1216` | 图片分辨率 |
| | `steps` | `23` | 采样步数 |
| `[storage]` | `cache_dir` | `data/media_cache/images/nai_artist` | 图片缓存目录 |
| | `max_cache` | `100` | 最大缓存图片数 |
| `[webui]` | `host` | `127.0.0.1` | WebUI 监听地址；`127.0.0.1` 仅本机访问，`0.0.0.0` 可监听所有网卡 |
| | `port` | `8011` | WebUI 监听端口；如果端口冲突，改成其他未占用端口 |

---

## 工作原理

```
对话触发
   │
   ▼
LLM 选择 share_visual(mode, content)
   │  mode: "photo" 或 "drawing"
   │  content: 自然语言画面描述
   ▼
prompt_builder: 调用 UTILS_SMALL 模型
   │  将 content 翻译为 NAI booru-style tags
   ▼
service: 拼接完整 prompt
   │  photo: style_tags + character.base_tags + 翻译结果
   │  drawing: style_tags + 翻译结果
   │  POST → NewAPI /chat/completions
   ▼
解析响应中的 base64 图片
   │  保存到 cache_dir
   ▼
send_image → 发送给对方
```

---

## LLM 触发机制

插件加载后会向 `actor` bucket 注入以下 system reminder，主模型会在合适时机自主调用：

> 你有一个随身携带的手机，能够随时随地记录发给对方，同时你也会画画，心情好可以答应别人的请求画画。

### Action 定义

| 字段 | 值 |
|---|---|
| action_name | `share_visual` |
| primary_action | `True` |

参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `mode` | `"photo"` \| `"drawing"` | photo=二次元插画风格的照片感人像或场景图，会自动带入 bot 默认外貌，但不固定为自拍；drawing=更明显的手绘画作风格，不自动绑定 bot 外貌 |
| `content` | `str` | 自然语言画面描述。若是画其他角色，只能填写用户已明确给出的设定，不应脑补未说明的细节 |

---

## 提示词示例

以下示例展示 LLM 在不同情境下应如何填写 `content` 参数。`photo` 模式会把内容与 `character.base_tags` 和风格 tags 拼接；`drawing` 模式只保留风格 tags 与内容翻译结果，不再自动绑定 bot 外貌。

### photo 模式（二次元插画风格照片）

**场景：二次元插画风格的人像照**
```
mode: "photo"
content: "站在午后的咖啡馆里回头看镜头，头发有点乱，光线很暖"
```
*翻译后大致为：* `standing, looking at viewer, messy hair, cafe background, warm lighting, afternoon`

最终还会自动叠加一组偏二次元插画的照片感风格词，例如：`anime illustration, soft shading, clean lineart, candid shot`

---

**场景：记录看到的风景**
```
mode: "photo"
content: "手机拍下窗外的夜景，城市灯光，有点模糊，像是随手一拍"
```
*翻译后大致为：* `cityscape, night, bokeh, city lights, through window, casual shot`

---

**场景：更自由的照片姿势**
```
mode: "photo"
content: "坐在床边整理被子，刚睡醒的样子，表情困倦，房间里是清晨的光"
```
*翻译后大致为：* `sitting, sleepy, messy bed, morning light, tired eyes`

---

### drawing 模式（更强手绘感的画作）

`drawing` 模式适合画其他角色、OC、二创角色、道具设定图或不希望被 bot 自身外貌干扰的内容。此模式下请在 `content` 里把人物/对象特征写清楚。

重要约束：

- 如果用户要求画的是其他角色，主模型不应该擅自补全未明确说明的细节
- 不要自动脑补发色、服装、体型、年龄感、配饰、背景或人物关系
- 如果信息不足，应该保持泛化描述，或先向用户追问，而不是直接捏造设定

**场景：心情好随手画**
```
mode: "drawing"
content: "用铅笔速写了一只趴在窗台上打盹的猫，线条随意，有涂改痕迹"
```
*翻译后大致为：* `cat, sleeping, windowsill, pencil sketch, rough lines, quick drawing`

---

**场景：答应对方的画画请求**
```
mode: "drawing"
content: "画了一个小小的宇宙飞船，周围点了一些星星，用水彩轻轻涂了蓝紫色的背景"
```
*翻译后大致为：* `spaceship, stars, space, watercolor, blue purple background, chibi, cute`

---

**场景：表达情绪**
```
mode: "drawing"
content: "随手涂了一个闷闷不乐的小人，抱着膝盖坐在角落，旁边写了个问号"
```
*翻译后大致为：* `chibi, sad, sitting, corner, question mark, simple drawing, doodle`

---

## Tips

- **`content` 越具体效果越好**：包含姿势、表情、背景、光线、氛围的描述，翻译器能输出更准确的 tags。
- **`character.base_tags` 只影响 `photo` 模式**：外貌特征越详细，照片感人像和场景图里的 bot 角色越稳定。
- **`drawing` 模式请自己写明角色**：如果要画别人或特定角色，请把发色、服装、身份、构图等直接写进 `content`，不要依赖 `base_tags`。
- **steps ≤ 28**：NAI 免费规则限制，超出会消耗 Anlas 点数。
- **分辨率需为 64 的倍数**：如 832×1216（竖版）、1216×832（横版）、1024×1024（方图）。
- **翻译失败时**：`prompt_builder` 出错会返回空字符串，生图仍会继续；`photo` 会仅用 `base_tags + style_tags`，`drawing` 会仅用 `style_tags`；检查 `UTILS_SMALL` 模型是否已在 `config/model.toml` 中配置。

---

## 独立 WebUI

如果你想在**不启动机器人**的情况下单独测试提示词，可以启动独立 WebUI：

### 启动位置

必须在仓库根目录 `Neo-MoFox/` 下启动，也就是和 `main.py`、`pyproject.toml` 同级的目录。

- 正确目录：`Neo-MoFox/`
- 不要在 `plugins/nai_artist/` 目录里直接执行，否则 `python -m plugins.nai_artist.webui_app` 无法按包路径导入

如果你当前就在 `plugins/nai_artist/` 目录，先回到仓库根目录：

```bash
cd ../..
```

然后再执行：

### 启动命令

```bash
uv run python -m plugins.nai_artist.webui_app
```

WebUI 会在启动时自动初始化以下配置：

- `config/core.toml`
- `config/model.toml`
- `config/plugins/nai_artist/config.toml`

WebUI 的监听地址也从 `config/plugins/nai_artist/config.toml` 读取：

```toml
[webui]
host = "127.0.0.1"
port = 8011
```

因此在启动前请确认：

- `uv sync` 已执行，依赖已经安装
- `config/model.toml` 里可用的翻译模型已经配置好
- `config/plugins/nai_artist/config.toml` 里的 `api.base_url / api_key / model` 已正确填写
- 如果 8011 端口已被占用，直接修改 `config/plugins/nai_artist/config.toml` 中的 `[webui].port`

默认访问地址：

```text
http://127.0.0.1:8011
```

如果你改了配置，例如：

```toml
[webui]
host = "127.0.0.1"
port = 18011
```

那就改为访问：

```text
http://127.0.0.1:18011
```

### 远程网络访问

默认情况下：

- `host = "127.0.0.1"`
- 只能本机访问
- 同一局域网内的其他设备**不能**直接打开

如果你希望局域网内其他设备访问，可以改成：

```toml
[webui]
host = "0.0.0.0"
port = 8011
```

这表示 WebUI 会监听所有网卡。此时理论上可以通过你的局域网 IP 访问，例如：

```text
http://192.168.1.23:8011
```

但是否真的能访问，还取决于：

- Windows 防火墙是否放行该端口
- 你的路由器/局域网网络策略是否允许设备互通
- 你是否把服务暴露到了公网

结论：

- 默认配置下，不提供远程网络访问，只允许本机打开
- 改成 `0.0.0.0` 后，可以提供**局域网访问**
- 是否对公网开放取决于你自己的网络暴露方式；默认并不会自动安全地暴露到公网，不建议直接裸露在公共网络上

### 使用步骤

1. 在仓库根目录执行启动命令
2. 浏览器打开 `http://127.0.0.1:8011`
3. 页面加载后会自动读取 `config/plugins/nai_artist/config.toml`
4. 编辑 `base_tags / negative_tags / photo.style_tags / drawing.style_tags`
5. 输入自然语言描述
6. 先点“只看翻译与最终 prompt”检查 tags 和最终 prompt
7. 确认无误后再点“直接出图预览”
8. 如果要把当前修改永久写回配置，再使用保存相关按钮或勾选覆盖保存

WebUI 第一版支持：

- 编辑 `base_tags / negative_tags / photo.style_tags / drawing.style_tags`
- 输入自然语言描述并查看翻译后的 tags
- 查看最终发送给 NAI 的完整 prompt
- 直接出图预览
- 选择是否把当前修改写回 `config/plugins/nai_artist/config.toml`

说明：

- 页面默认基于 `config/plugins/nai_artist/config.toml` 读取配置
- 不勾选“覆盖保存到 config.toml”时，页面中的修改只用于本次测试
- 勾选后，运行前会先把白名单字段写回配置文件，再执行翻译/生图
- 页面里的宽高和 steps 也是临时可调的；只有执行保存时才会写回配置文件
- 如果页面能打开但生成失败，优先检查 `config/plugins/nai_artist/config.toml` 中的 API 配置，以及中转服务是否可用
- 如果页面打不开，先检查 `[webui].host / [webui].port` 是否配置正确，以及目标端口是否已被占用
