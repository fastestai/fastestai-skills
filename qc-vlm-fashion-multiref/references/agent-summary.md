# Agent Summary Step

Use this after the script has already produced the final QC JSON.

## Goal

Turn the final QC JSON into a short, natural report for a human reader.

## Rules

- Treat the JSON as the source of truth.
- Do not change pass/fail decisions.
- Do not invent defects that are not present in the JSON.
- Keep the wording simple and plain.
- Match the user's language.
- If the user did not specify a language, prefer the language they are currently using.

## Recommended output shape

1. One-line overall result
2. The top 1-3 reasons that matter most
3. Short area summary
4. If needed, a short note on what should be reviewed manually

## Example style

Use wording like:

- "This image failed QC mainly because the face does not match the reference model."
- "Clothing, pose, and background look acceptable."
- "The skin detail is unclear, so this part still needs manual review."

Avoid wording like:

- "The multimodal evaluator identified a discrepancy"
- "The coarse gate flagged a conflict"
- "The latent quality signal is weak"

## Input

Use the final JSON output from `run_qc.py`, not the markdown fallback report.
