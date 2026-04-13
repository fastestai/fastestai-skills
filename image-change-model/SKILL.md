---
name: image-change-model
description: "两步调用换模特工作流：先运行 prompt workflow 生成 final_prompt 和标准化输入，再把结果作为 input_data 传给图片生成 workflow。Use when changing the model in a product image by chaining workflow IDs 694caf01b7c2c3990ca7b8bf and 694e206fc1c0b24dc831ad8b with wf run."
---

# Image Change Model

这个 skill 用于串联两个远程 workflow，完成「换模特」图片生成：

1. `694caf01b7c2c3990ca7b8bf`：先根据输入图片和参考模特，产出带 `final_prompt` 的中间结果。
2. `694e206fc1c0b24dc831ad8b`：再把中间结果作为 `input_data` 传入，生成最终图片。

默认使用远程执行：

```sh
wf run <WORKFLOW_ID>
```

## 如何查看 Workflow Input

如果需要重新确认某个 workflow 的当前输入定义，可请求：

```text
https://www.maybe.ai/api/trpc/getWorkflowDetail?input=%7B%22artifact_id%22%3A%22<workflow_id>%22%7D
```

读取返回 JSON 里的 `result.data.variables` 即可。

## 第一步：Prompt Workflow

- Workflow ID: `694caf01b7c2c3990ca7b8bf`
- 作用：生成中间 dataframe，并补出后续生成需要的 `final_prompt`

### 可覆盖输入

- `--case`
  - 业务场景。这个 skill 固定使用 `change-model`。
  - 除非你明确要切到别的 sheet，否则不要改。
- `--product_image_url`
  - 输入模特图 URL（数组）。上传几张出几张。
- `--reference_image_url`
  - 参考模特图 URL（非必选）。留空则由模型自行生成。
- `--target_market`
  - 目标国家。默认 `China`。
- `--aspect_ratio`
  - 生成比例。未知时用 `auto`。
- `--resolution`
  - 清晰度。可用值按当前 workflow 描述为 `1K` / `2K`，未知时用 `1K`。
- `--user_description`
  - 可选文本补充，用于描述模特特征（非必填，不能自定义出图张数）。
- `--llm_model`
  - workflow 定义里存在这个变量，但当前第一步流程本身没有实际消费它。正常情况下保留默认值即可。

### 第一步输出

第一步会产出一个 dataframe。第二步实际需要其中这些字段：

- `case`
- `product_image_url`
- `reference_image_url`
- `aspect_ratio`
- `resolution`
- `image_count`
- `final_prompt`

第一步当前还会带出 `user_description` 和 `target_market`。这些额外字段可以保留，不影响后续理解。

### 示例命令

```sh
wf run 694caf01b7c2c3990ca7b8bf \
  --case "change-model" \
  --product_image_url '["<SOURCE_IMAGE_URL>"]' \
  --reference_image_url "" \
  --target_market "China" \
  --aspect_ratio "auto" \
  --resolution "1K" \
  --user_description ""
```

运行完成后，按 `run-workflow` skill 的约定，从保存下来的 `output/<timestamp>.json` 里取出第一步结果。

## 第二步：Result Workflow

- Workflow ID: `694e206fc1c0b24dc831ad8b`
- 作用：消费第一步结果，生成最终图片

### 可覆盖输入

- `--input_data`
  - 一个 JSON array。通常直接使用第一步输出的完整 JSON。
- `--llm_model`
  - 最终图片生成模型。默认值是 `google/gemini-3.1-flash-image-preview`。

### `input_data` 需要包含的字段

第二步 workflow 的默认样例里包含这些列：

- `case`
- `product_image_url`
- `reference_image_url`
- `model_description`
- `aspect_ratio`
- `resolution`
- `image_count`
- `final_prompt`

按 workflow 定义推断，第二步实际下游会读取的是：

- `case`
- `product_image_url`
- `reference_image_url`
- `aspect_ratio`
- `resolution`
- `image_count`
- `final_prompt`

也就是说，第一步输出里没有 `model_description` 不是这个串联流程的核心问题，因为当前第二步流程没有消费该字段。

如果后续 workflow 校验变严，要求显式存在 `model_description`，给每一行补一个空字符串即可。

### 第二步输出

第二步最终输出 dataframe，主要字段为：

- `url`
- `size`
- `model`
- `created`

### 示例命令

```sh
wf run 694e206fc1c0b24dc831ad8b \
  --input_data '[{"case":"change-model","product_image_url":"<SOURCE_IMAGE_URL>","reference_image_url":"","aspect_ratio":"auto","resolution":"1K","user_description":"","image_count":1,"final_prompt":"<FINAL_PROMPT_FROM_STEP_1>"}]'
```

如果你要直接复用第一步保存下来的结果文件，更接近实际执行的方式是：

```sh
STEP1_FILE="output/<STEP1_TIMESTAMP>.json"
wf run 694e206fc1c0b24dc831ad8b \
  --input_data "$(cat "$STEP1_FILE")"
```

## 两步调用方式

1. 先运行第一步 workflow `694caf01b7c2c3990ca7b8bf`，生成带 `final_prompt` 的中间 dataframe。
2. 读取第一步保存下来的 `output/<timestamp>.json`。
3. 把这个 JSON array 原样传给第二步 workflow `694e206fc1c0b24dc831ad8b` 的 `--input_data`。
4. 读取第二步输出里的 `url`，这就是最终生成图。

## 推荐的执行心智

- 不要单独手写第二步的 `final_prompt`。先跑第一步，让 workflow 生成它。
- 这个 skill 固定围绕 `case=change-model` 工作，不要把它当成通用 case 切换器。
- 远程执行优先。只有在调试 workflow 逻辑时，再考虑 `--mode local`。
