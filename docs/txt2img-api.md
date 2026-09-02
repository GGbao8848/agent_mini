# 文生图（txt2img）模型调用 API 文档

本地文生图服务基于 **A1111 / Stable Diffusion WebUI Forge 兼容接口**，后端模型为
`z_image_turbo-Q8_0`（Z-Image Turbo，GGUF Q8_0 量化，蒸馏加速模型，4~8 步即可出图）。

Agent Core 的 `generate_image` 工具就是对这个端点的封装（见 `src/agent_core/builtins/image.py`）。

## 1. 服务信息

| 项目 | 值 |
| --- | --- |
| 服务地址 | `http://10.10.10.169:18542` |
| 环境变量 | `AGENT_CORE_IMAGE_API_BASE_URL` |
| 接口风格 | A1111 / Forge 兼容（`/sdapi/v1/*`） |
| 当前模型 | `z_image_turbo-Q8_0` |
| 鉴权 | 无（局域网服务，不需要 API Key） |
| 出图上限 | 单图面积约 **0.85MP**（实测 `1024×1024`=1.05MP 返回 HTTP 500）；安全区 ≤ `768×768` |
| 单次超时 | 建议 300s（Agent 工具即 300s） |

## 2. 核心端点

### `POST /sdapi/v1/txt2img`

文本生成图像。

**请求头：** `Content-Type: application/json`

**请求体（JSON）：**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `prompt` | string | ✅ | 正向提示词，描述画面内容、风格、光线等 |
| `negative_prompt` | string | 否 | 负向提示词，排除的内容（如 `blurry, low quality`） |
| `width` | int | 否 | 宽度像素，默认 512；建议为 8 的倍数 |
| `height` | int | 否 | 高度像素，默认 512；建议为 8 的倍数 |
| `steps` | int | 否 | 采样步数。Turbo 模型 4~8 步即可，默认 8 |
| `cfg_scale` | float | 否 | 提示词遵循度（CFG），Turbo 模型建议 1.0，默认 1.0 |
| `seed` | int | 否 | 随机种子，固定后可复现同一张图 |
| `sampler_name` | string | 否 | 采样器，Turbo 模型建议使用 `NONE`（默认） |
| `batch_size` | int | 否 | 一次生成的张数，默认 1（返回多个 base64） |

**响应（HTTP 200）：**

```json
{
  "images": ["iVBORw0KGgoAAAANSUhEUgAA..."],
  "parameters": {
    "prompt": "a red cube on a white table",
    "width": 512,
    "height": 512,
    "steps": 4,
    "cfg_scale": 1.0
  },
  "info": "{...JSON 字符串，含 all_seeds / all_prompts / infotexts 等生成信息...}"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `images` | string[] | 每张图为 **PNG 的 Base64**，可直接 `base64.b64decode` 后落盘 |
| `parameters` | object | 回显本次请求参数 |
| `info` | string | JSON 字符串；解析后含 `all_seeds`（实际种子）、`all_prompts`、`infotexts` 等 |

**错误（HTTP 500）：** `{"error": "..."}`，例如请求面积超限时返回
`{"error": "generate_image returned no results"}`。

## 3. 调用示例

### curl

```bash
curl -X POST http://10.10.10.169:18542/sdapi/v1/txt2img \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a red cube on a white table, minimalist photo style",
    "negative_prompt": "blurry, low quality",
    "width": 512,
    "height": 512,
    "steps": 8,
    "cfg_scale": 1.0,
    "seed": 42
  }' \
  -o response.json

# 取回并保存 PNG
python3 -c "
import json, base64
d = json.load(open('response.json'))
open('out.png', 'wb').write(base64.b64decode(d['images'][0]))
print('saved out.png', len(d['images']), 'image(s)')
"
```

### Python（httpx）

```python
import base64
import httpx

resp = httpx.post(
    "http://10.10.10.169:18542/sdapi/v1/txt2img",
    json={
        "prompt": "a red cube on a white table, minimalist photo style",
        "negative_prompt": "blurry, low quality",
        "width": 512,
        "height": 512,
        "steps": 8,
        "cfg_scale": 1.0,
    },
    timeout=300.0,
)
resp.raise_for_status()
data = resp.json()
png = base64.b64decode(data["images"][0])  # PNG 字节
open("out.png", "wb").write(png)
```

### 通过 Agent 调用（推荐）

Agent 内置了封装好的 `generate_image` 工具，会自动处理面积钳制、落盘、产物注册，
无需直接接触 HTTP：

```json
{
  "tool": "generate_image",
  "arguments": {
    "prompt": "a red cube on a white table, minimalist photo style",
    "width": 512,
    "height": 512,
    "steps": 8,
    "cfg_scale": 1.0
  }
}
```

- 返回生成图片的 **绝对路径**（保存在任务目录 `images/` 下）；
- 之后调用 `view_image` 传入该路径即可让视觉模型查看图片、验证效果。

## 4. 注意事项（实测结论）

1. **面积限制**：单图面积超过约 0.85MP 时后端直接 HTTP 500。Agent 工具已内置钳制：
   超过 `768×768`（约 0.59MP）会自动等比缩到安全面积，并保持宽高为 8 的倍数。
2. **步数与 CFG**：Turbo 模型建议 `steps=8`、`cfg_scale=1.0`；步数太多反而可能过拟合。
3. **负向提示词**：已实测支持，可用来排除模糊、低质量、多余物体等。
4. **种子**：传 `seed` 可复现；不传则每次随机（`info.all_seeds` 可读到实际使用的种子）。
5. **超时**：生图可能较慢，客户端请设置 300s 超时，避免中途断连。
6. **无鉴权**：服务在局域网内裸奔，勿暴露到公网。

## 5. 其他可用端点

| 端点 | 用途 |
| --- | --- |
| `GET /sdapi/v1/options` | 查看/设置服务配置，如 `sd_model_checkpoint` |
| `GET /sdapi/v1/samplers` | 列出可用采样器（`default` / `euler` / `dpm++2m` 等） |
| `GET /sdapi/v1/sd-models` | 列出已加载的模型文件 |

## 6. 常见错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `HTTP 500 generate_image returned no results` | 面积超限或后端生成失败 | 把宽高缩到 `≤768×768` 重试 |
| 连接超时 / `Image service unreachable` | 服务未启动或网络不通 | 确认服务在 `10.10.10.169:18542` 存活 |
| 返回空 `images` | 后端异常 | 检查服务日志，稍后重试 |
