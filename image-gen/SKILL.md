---
name: image-gen
description: "通用图片生成：调用 workflow 698fe27474479805ea70d6ae，根据 prompt 和可选输入图片生成图片，支持多种模型、分辨率和宽高比。Use when generating images from a prompt, optionally with input reference images."
---

# Image Gen — 通用图片生成

调用远程 workflow `698fe27474479805ea70d6ae`，根据用户描述（prompt）和可选的输入图片生成图片。

```sh
wf run 698fe27474479805ea70d6ae
```

## 输入参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `user_description` | string | ✅ | — | 生成图片的 prompt |
| `product_image_url` | string[] | ❌ | `[]` | 输入图片的 URL 数组，没有时传空数组 |
| `llm_model` | string enum | ❌ | `google/gemini-3-pro-image-preview` | 生成模型，见下方可选值 |
| `resolution` | string enum | ❌ | `1K` | 分辨率 |
| `aspect_ratio` | string enum | ❌ | `auto` | 宽高比 |

### `llm_model` 可选值

- `fal-ai/gpt-image-1.5/edit`
- `fal-ai/qwen-image-edit-2511`
- `google/gemini-3-pro-image-preview`（默认）
- `google/gemini-3.1-flash-image-preview`
- `fal-ai/nano-banana-2/edit`
- `fal-ai/nano-banana-pro/edit`

### `resolution` 可选值

`1K`（默认）| `2K` | `4K`

### `aspect_ratio` 可选值

`21:9` | `16:9` | `3:2` | `4:3` | `5:4` | `1:1` | `4:5` | `3:4` | `2:3` | `9:16` | `auto`（默认）

## 示例命令

### 纯文本生成（无输入图片）

```sh
wf run 698fe27474479805ea70d6ae \
  --user_description "一只穿着宇航服的猫站在月球表面" \
  --product_image_url '[]'
```

### 带输入图片生成

```sh
wf run 698fe27474479805ea70d6ae \
  --user_description "将这张照片转换为水彩画风格" \
  --product_image_url '["https://example.com/photo.jpg"]' \
  --llm_model "google/gemini-3.1-flash-image-preview" \
  --resolution "2K" \
  --aspect_ratio "1:1"
```

## 输出

workflow 输出 dataframe，主要字段：

- `url` — 生成图片的 URL
- `size` — 图片大小
- `model` — 使用的模型
- `created` — 创建时间

运行完成后，结果保存在 `output/<timestamp>.json`。
