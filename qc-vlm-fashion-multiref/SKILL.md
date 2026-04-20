---
name: qc-vlm-fashion-multiref
description: "Use when performing VLM-based QC for generated fashion images using a result image plus model, garment, pose, and/or background references. Supports 4-image and 5-image cases, including a shared pose/background reference image."
---

# QC VLM Fashion Multi-Reference

Portable skill for first-pass QC of generated fashion images with multiple references.

## When to use

Use this skill when the user wants a reusable QC workflow that:

- compares a generated result image against one or more references
- supports `result`, `model_reference`, `garment_reference`, `pose_reference`, and `background_reference`
- allows one image to carry multiple roles, such as a shared pose/background reference
- can run either the full QC set or only selected checks such as `background` or `identity`
- uses `wf` tool `llm-multimodal-invoke` as the multimodal backend

## Inputs

The skill is role-based, not count-based.

Required roles:

- There is no single global required role set anymore.
- The required roles are inferred from the checks being run.
- `result` is required by every current check.

Optional roles:

- `pose_reference`
- `background_reference`

Common 4-image case:

- `result`
- `model_reference`
- `garment_reference`
- `reference` (shared as both `pose_reference` and `background_reference`)

Each image source may be either:

- a public URL
- a local file path

If a source is already a URL, the script uses it directly.
If a source is local, the script uploads it with the sibling `cos-upload` skill and then uses the returned public URL.

## Default workflow

1. Normalize input roles.
2. Resolve all image sources to public URLs.
3. Decide which checks to run.
   - If `--checks` is provided, run exactly those checks.
   - If `--checks` is omitted, auto-select every check supported by the provided inputs.
4. Run a quick first-pass check over the selected checks.
5. If the quick check result is not a hard fail, or if `--force-detailed` is set, run the selected detailed evaluators.
5. Aggregate all dimension results into a single structured JSON report.
6. Optionally produce two human-facing views:
   - the script-rendered markdown fallback report
   - an agent-written natural summary based on the final JSON

The final JSON includes both:

- `quality_score`: a script-calculated score meant to reflect overall completion quality
- `overall_status`: the business decision result (`pass`, `fail`, or `uncertain`)

These are intentionally separate. A result may have a moderate score but still fail business rules because a key item failed.

Read [references/rubric.md](references/rubric.md) when changing scoring logic.
Read the matching `references/prompt-*.md` files when changing evaluator behavior.
Read [references/agent-summary.md](references/agent-summary.md) when the user wants a more natural human summary.

## Commands

Simple 4-image invocation:

```bash
python .agents/skills/qc-vlm-fashion-multiref/scripts/run_qc.py \
  --result https://example.com/result.jpg \
  --model-reference https://example.com/model.jpg \
  --garment-reference https://example.com/garment.jpg \
  --reference https://example.com/pose-and-bg.jpg
```

5-role invocation:

```bash
python .agents/skills/qc-vlm-fashion-multiref/scripts/run_qc.py \
  --result /path/to/result.jpg \
  --model-reference /path/to/model.jpg \
  --garment-reference /path/to/garment.jpg \
  --pose-reference /path/to/pose.jpg \
  --background-reference /path/to/background.jpg
```

Advanced JSON input:

```bash
python .agents/skills/qc-vlm-fashion-multiref/scripts/run_qc.py \
  --input-json '{"images":[{"source":"result.jpg","roles":["result"]},{"source":"model.jpg","roles":["model_reference"]},{"source":"garment.jpg","roles":["garment_reference"]},{"source":"ref.jpg","roles":["pose_reference","background_reference"]}]}'
```

Useful flags:

- `--checks identity,background`: run only the selected checks
- `--force-detailed`: continue into detailed evaluators even if coarse stage already failed
- `--coarse-only`: stop after the coarse gate
- `--stdout-format markdown|json|both`: choose what is printed to stdout; default is markdown
- `--output-json PATH`: write the structured JSON report to a file
- `--output-md PATH`: write the human-readable markdown report to a file
- `--model gemini-3-flash`: override the default multimodal model

## Notes

- The script assumes one source per role. One source may serve multiple roles, but one role may not map to multiple different sources.
- If `--checks` is omitted, the script auto-selects every check supported by the provided inputs.
- If `--checks` is provided, the script validates that all required roles for those checks are present.
- The script-rendered markdown is a stable fallback report.
- When the user wants a better human-facing summary, the agent should read the final JSON and write a short natural-language report using `references/agent-summary.md`.
- Keep the JSON as the source of truth. The agent summary must not override it.
