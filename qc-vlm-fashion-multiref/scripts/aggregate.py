from __future__ import annotations

from typing import Any

from schema import CoarseResult, DimensionResult, QCReport


DIMENSION_ORDER = [
    "identity",
    "garment",
    "pose",
    "background",
    "fusion",
    "quality",
]


def sort_dimensions(dimensions: list[DimensionResult]) -> list[DimensionResult]:
    order = {name: index for index, name in enumerate(DIMENSION_ORDER)}
    return sorted(dimensions, key=lambda item: order.get(item.dimension, 999))


def build_summary(dimensions: list[DimensionResult]) -> dict[str, Any]:
    counts = {
        "pass": 0,
        "fail": 0,
        "uncertain": 0,
        "missing_input": 0,
        "not_applicable": 0,
        "skipped_after_coarse": 0,
    }
    failures: list[dict[str, str]] = []
    uncertain: list[dict[str, str]] = []

    for dimension in dimensions:
        counts[dimension.status] = counts.get(dimension.status, 0) + 1
        if dimension.status == "fail":
            failures.append(
                {
                    "dimension": dimension.dimension,
                    "summary": dimension.summary,
                }
            )
        if dimension.status in {"uncertain", "missing_input"}:
            uncertain.append(
                {
                    "dimension": dimension.dimension,
                    "summary": dimension.summary,
                }
            )

    return {
        "counts": counts,
        "failures": failures,
        "uncertain_or_missing": uncertain,
    }


def decide_overall_status(dimensions: list[DimensionResult], coarse: CoarseResult) -> str:
    evaluated_dimensions = [
        dimension
        for dimension in dimensions
        if dimension.status
        not in {"missing_input", "not_applicable", "skipped_after_coarse"}
    ]
    if any(dimension.status == "fail" for dimension in dimensions):
        return "fail"
    if coarse.status == "fail" and not dimensions:
        return "fail"
    if coarse.status == "fail" and evaluated_dimensions:
        return "uncertain"
    if any(dimension.status in {"uncertain", "missing_input"} for dimension in dimensions):
        return "uncertain"
    if coarse.status == "uncertain":
        return "uncertain"
    return "pass"


def build_report(
    coarse: CoarseResult,
    dimensions: list[DimensionResult],
    inputs: Any,
    metadata: dict[str, Any],
) -> QCReport:
    ordered_dimensions = sort_dimensions(dimensions)
    summary = build_summary(ordered_dimensions)
    summary["coarse_status"] = coarse.status
    summary["coarse_detailed_conflict"] = (
        coarse.status == "fail"
        and not any(dimension.status == "fail" for dimension in ordered_dimensions)
        and any(
            dimension.status
            not in {"missing_input", "not_applicable", "skipped_after_coarse"}
            for dimension in ordered_dimensions
        )
    )
    return QCReport(
        overall_status=decide_overall_status(ordered_dimensions, coarse),
        summary=summary,
        coarse=coarse,
        dimensions=ordered_dimensions,
        inputs=inputs,
        metadata=metadata,
    )
