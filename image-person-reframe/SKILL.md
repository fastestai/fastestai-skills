---
name: image-person-reframe
description: "使用 Fastest AI 的 `POST /v1/tool/image/person_reframe` 接口做人物构图对齐。Use when aligning the framing or composition of one image to match a target image by calling the Fastest AI person_reframe API with curl."
---

# Image Person Reframe

这个 skill 用于调用 Fastest AI 的人物构图对齐接口。

它的目标是：

- 让 `ref` 图片作为待处理图片
- 让 `target` 图片作为目标构图
- 通过一次 `curl POST` 请求完成调用

## 接口信息

- Method: `POST`
- URL: `https://api.fastest.ai/v1/tool/image/person_reframe`

## 请求参数

- `ref`
  - 要被处理的图片 URL。
  - 可以理解为“源图”或“待调整构图的图片”。
- `target`
  - 被对齐的目标图片 URL。
  - 可以理解为“目标构图图”。

## 调用方式

默认使用 `curl` 直接发起 `POST` 请求：

```sh
curl -X POST 'https://api.fastest.ai/v1/tool/image/person_reframe' \
  -H 'Content-Type: application/json' \
  -d '{
    "ref": "<REF_IMAGE_URL>",
    "target": "<TARGET_IMAGE_URL>"
  }'
```

## 示例

```sh
curl -X POST 'https://api.fastest.ai/v1/tool/image/person_reframe' \
  -H 'Content-Type: application/json' \
  -d '{
    "ref": "https://example.com/reference.jpg",
    "target": "https://example.com/target.jpg"
  }'
```

## 参数含义说明

- `ref` 是要被处理的图片，不是目标图。
- `target` 是被对齐的目标，不是输出图。
- 两个字段都应传可访问的图片 URL。

## 推荐的执行心智

- 不要把 `ref` 和 `target` 传反。
- 这个 skill 只做单次接口调用，不涉及 `wf run`。
- 如果要批量处理，多组图片应分别发起多次请求。
- 如果当前环境还要求鉴权，优先补项目里已有的认证头，不要臆造新的 header。

## 输出处理

- 该接口的返回内容以实际响应为准。
- 拿到响应后，优先读取其中的结果图片地址、任务结果或错误信息。
- 如果返回失败，先检查图片 URL 是否可访问，以及 `ref` / `target` 是否传反。
