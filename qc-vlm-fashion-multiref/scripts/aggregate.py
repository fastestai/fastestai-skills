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

ITEM_WEIGHTS = {
    "model_face": 18,
    "makeup_hair": 6,
    "body_skin_tone": 4,
    "skin_evenness": 2,
    "garment_shape": 12,
    "pattern_details": 8,
    "material_texture": 4,
    "garment_color": 3,
    "wearing_naturalness": 3,
    "overall_pose": 8,
    "hand_head_details": 4,
    "framing_proportion": 3,
    "background_content": 4,
    "background_tone": 2,
    "background_texture": 2,
    "background_lighting": 2,
    "edge_blending": 6,
    "lighting_consistency": 4,
    "base_image_quality": 5,
}

STATUS_SCORES = {
    "pass": 1.0,
    "uncertain": 0.5,
    "fail": 0.0,
}

KEY_DECISION_ITEMS = {
    "model_face",
    "garment_shape",
    "pattern_details",
    "overall_pose",
    "background_content",
    "edge_blending",
    "base_image_quality",
}


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


def build_score_breakdown(dimensions: list[DimensionResult]) -> dict[str, Any]:
    dimension_rows: list[dict[str, Any]] = []
    total_possible = 0.0
    total_earned = 0.0

    for dimension in dimensions:
        item_rows: list[dict[str, Any]] = []
        dimension_possible = 0.0
        dimension_earned = 0.0

        for item in dimension.items:
            weight = ITEM_WEIGHTS.get(item.name, 0)
            if weight <= 0:
                continue
            status_value = STATUS_SCORES.get(item.status, 0.5)
            earned = weight * status_value
            dimension_possible += weight
            dimension_earned += earned
            item_rows.append(
                {
                    "name": item.name,
                    "status": item.status,
                    "weight": weight,
                    "earned": round(earned, 2),
                    "possible": weight,
                }
            )

        if dimension_possible > 0:
            total_possible += dimension_possible
            total_earned += dimension_earned

        dimension_rows.append(
            {
                "dimension": dimension.dimension,
                "status": dimension.status,
                "earned": round(dimension_earned, 2),
                "possible": round(dimension_possible, 2),
                "score": round((dimension_earned / dimension_possible) * 100, 2)
                if dimension_possible
                else None,
                "items": item_rows,
            }
        )

    normalized_score = (
        round((total_earned / total_possible) * 100, 2) if total_possible else None
    )
    return {
        "score": normalized_score,
        "earned": round(total_earned, 2),
        "possible": round(total_possible, 2),
        "dimensions": dimension_rows,
    }


def build_decision_reasons(dimensions: list[DimensionResult], coarse: CoarseResult) -> list[str]:
    reasons: list[str] = []

    for dimension in dimensions:
        for item in dimension.items:
            if item.name in KEY_DECISION_ITEMS and item.status == "fail":
                reasons.append(
                    f"Key item failed: {dimension.dimension}.{item.name}."
                )

    if any(dimension.status == "missing_input" for dimension in dimensions):
        reasons.append("One or more required checks could not run because input was missing.")

    if any(dimension.status == "uncertain" for dimension in dimensions):
        reasons.append("Some areas were unclear and still need manual review.")

    if coarse.status == "fail" and not reasons:
        reasons.append("The quick check found a major visible issue.")

    if coarse.status == "uncertain" and not reasons:
        reasons.append("The quick check could not make a confident decision.")

    if not reasons:
        reasons.append("All required checks passed without a key failure.")

    return reasons


def decide_overall_status(dimensions: list[DimensionResult], coarse: CoarseResult) -> str:
    evaluated_dimensions = [
        dimension
        for dimension in dimensions
        if dimension.status
        not in {"missing_input", "not_applicable", "skipped_after_coarse"}
    ]
    if any(
        item.name in KEY_DECISION_ITEMS and item.status == "fail"
        for dimension in dimensions
        for item in dimension.items
    ):
        return "fail"
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
    score_breakdown = build_score_breakdown(ordered_dimensions)
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
        quality_score=score_breakdown["score"],
        score_breakdown=score_breakdown,
        decision_reasons=build_decision_reasons(ordered_dimensions, coarse),
        summary=summary,
        coarse=coarse,
        dimensions=ordered_dimensions,
        inputs=inputs,
        metadata=metadata,
    )
