from __future__ import annotations

from typing import Any


STATUS_ICON = {
    "pass": "Pass",
    "fail": "Fail",
    "uncertain": "Needs Review",
    "missing_input": "Missing Input",
    "not_applicable": "N/A",
    "skipped_after_coarse": "Skipped",
}


def _fmt_status(status: str) -> str:
    return STATUS_ICON.get(status, status.upper())


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []

    overall_status = report.get("overall_status", "uncertain")
    coarse = report.get("coarse", {})
    summary = report.get("summary", {})
    dimensions = list(report.get("dimensions") or [])

    lines.append("# QC Report")
    lines.append("")
    lines.append(f"Final result: `{_fmt_status(overall_status)}`")
    if report.get("quality_score") is not None:
        lines.append(f"Quality score: `{report['quality_score']:.2f}/100`")
    lines.append(f"Quick check: `{_fmt_status(coarse.get('status', 'uncertain'))}`")

    metadata = report.get("metadata") or {}
    if metadata.get("model"):
        lines.append(f"Model: `{metadata['model']}`")
    if metadata.get("generated_at"):
        lines.append(f"Generated at: `{metadata['generated_at']}`")

    decision_reasons = list(report.get("decision_reasons") or [])
    if decision_reasons:
        lines.append("")
        lines.append("## Why It Was Marked This Way")
        for reason in decision_reasons:
            lines.append(f"- {reason}")

    failure_summaries = list(summary.get("failures") or [])
    uncertain_summaries = list(summary.get("uncertain_or_missing") or [])

    if coarse.get("summary"):
        lines.append("")
        lines.append("## Quick Check Summary")
        lines.append(coarse["summary"])

    obvious_failures = list(coarse.get("obvious_failures") or [])
    if obvious_failures:
        lines.append("")
        lines.append("## Main Problems Found Early")
        for item in obvious_failures:
            lines.append(f"- {item}")

    if failure_summaries:
        lines.append("")
        lines.append("## Failed Checks")
        for item in failure_summaries:
            lines.append(
                f"- `{item.get('dimension', 'unknown')}`: {item.get('summary', '').strip()}"
            )

    if uncertain_summaries:
        lines.append("")
        lines.append("## Checks That Need Review")
        for item in uncertain_summaries:
            lines.append(
                f"- `{item.get('dimension', 'unknown')}`: {item.get('summary', '').strip()}"
            )

    if dimensions:
        lines.append("")
        lines.append("## Results By Check")
        for dimension in dimensions:
            dimension_score = _find_dimension_score(
                report.get("score_breakdown") or {}, dimension["dimension"]
            )
            score_suffix = (
                f" ({dimension_score:.0f}/100)" if dimension_score is not None else ""
            )
            lines.append(
                f"- `{dimension['dimension']}`: `{_fmt_status(dimension['status'])}`{score_suffix}"
            )

        detailed_dimensions = [
            dimension
            for dimension in dimensions
            if dimension.get("status") in {"fail", "uncertain", "missing_input"}
            or any(
                item.get("status") in {"fail", "uncertain"}
                for item in dimension.get("items") or []
            )
        ]
        if not detailed_dimensions:
            detailed_dimensions = dimensions

        lines.append("")
        lines.append("## Details")
        for dimension in detailed_dimensions:
            lines.append("")
            lines.append(f"### {dimension['dimension']} `{_fmt_status(dimension['status'])}`")
            if dimension.get("summary"):
                lines.append(dimension["summary"])
            for item in dimension.get("items") or []:
                item_status = item.get("status", "uncertain")
                if item_status == "pass" and dimension.get("status") == "pass":
                    continue
                lines.append(
                    f"- `{item.get('name', 'unknown')}` `{_fmt_status(item_status)}`: "
                    f"{item.get('reason', '').strip()}"
                )

    return "\n".join(lines).strip() + "\n"


def _find_dimension_score(score_breakdown: dict[str, Any], dimension_name: str) -> float | None:
    for row in score_breakdown.get("dimensions") or []:
        if row.get("dimension") == dimension_name:
            return row.get("score")
    return None
