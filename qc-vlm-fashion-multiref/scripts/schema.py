from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_ITEM_STATUSES = {"pass", "fail", "uncertain"}
VALID_DIMENSION_STATUSES = {
    "pass",
    "fail",
    "uncertain",
    "missing_input",
    "not_applicable",
    "skipped_after_coarse",
}
VALID_OVERALL_STATUSES = {"pass", "fail", "uncertain"}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


@dataclass
class InputImage:
    source: str
    roles: list[str]
    resolved_url: str | None = None
    uploaded: bool = False


@dataclass
class NormalizedInputs:
    images: list[InputImage]
    role_to_source: dict[str, str]
    role_to_url: dict[str, str]

    def shared_sources(self) -> list[dict[str, Any]]:
        mapping: dict[str, list[str]] = {}
        for role, source in self.role_to_source.items():
            mapping.setdefault(source, []).append(role)
        return [
            {"source": source, "roles": roles}
            for source, roles in mapping.items()
            if len(roles) > 1
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "images": [asdict(image) for image in self.images],
            "role_to_source": dict(self.role_to_source),
            "role_to_url": dict(self.role_to_url),
            "shared_sources": self.shared_sources(),
        }


@dataclass
class EvaluationItem:
    name: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in VALID_ITEM_STATUSES:
            self.status = "uncertain"
        self.name = _clean_text(self.name)
        self.reason = _clean_text(self.reason)


@dataclass
class DimensionResult:
    dimension: str
    status: str
    summary: str
    confidence: str = "medium"
    items: list[EvaluationItem] = field(default_factory=list)
    compared_roles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALID_DIMENSION_STATUSES:
            self.status = "uncertain"
        self.summary = _clean_text(self.summary)
        self.confidence = _clean_text(self.confidence) or "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status,
            "summary": self.summary,
            "confidence": self.confidence,
            "compared_roles": list(self.compared_roles),
            "items": [asdict(item) for item in self.items],
        }


@dataclass
class CoarseResult:
    status: str
    summary: str
    obvious_failures: list[str] = field(default_factory=list)
    suspect_dimensions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALID_OVERALL_STATUSES:
            self.status = "uncertain"
        self.summary = _clean_text(self.summary)
        self.obvious_failures = [_clean_text(item) for item in self.obvious_failures if _clean_text(item)]
        self.suspect_dimensions = [
            _clean_text(item) for item in self.suspect_dimensions if _clean_text(item)
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QCReport:
    overall_status: str
    quality_score: float | None
    score_breakdown: dict[str, Any]
    decision_reasons: list[str]
    summary: dict[str, Any]
    coarse: CoarseResult
    dimensions: list[DimensionResult]
    inputs: NormalizedInputs
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.overall_status not in VALID_OVERALL_STATUSES:
            self.overall_status = "uncertain"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "quality_score": self.quality_score,
            "score_breakdown": self.score_breakdown,
            "decision_reasons": list(self.decision_reasons),
            "summary": self.summary,
            "coarse": self.coarse.to_dict(),
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "inputs": self.inputs.to_dict(),
            "metadata": dict(self.metadata),
        }


def build_coarse_result(payload: dict[str, Any]) -> CoarseResult:
    return CoarseResult(
        status=_clean_text(payload.get("status")) or "uncertain",
        summary=_clean_text(payload.get("summary")),
        obvious_failures=list(payload.get("obvious_failures") or []),
        suspect_dimensions=list(payload.get("suspect_dimensions") or []),
    )


def build_dimension_result(
    payload: dict[str, Any],
    dimension: str,
    item_names: list[str],
    compared_roles: list[str],
) -> DimensionResult:
    raw_items = payload.get("items") or []
    item_lookup: dict[str, EvaluationItem] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        name = _clean_text(raw_item.get("name"))
        if not name:
            continue
        item_lookup[name] = EvaluationItem(
            name=name,
            status=_clean_text(raw_item.get("status")) or "uncertain",
            reason=_clean_text(raw_item.get("reason")),
        )

    items: list[EvaluationItem] = []
    for item_name in item_names:
        items.append(
            item_lookup.get(
                item_name,
                EvaluationItem(
                    name=item_name,
                    status="uncertain",
                    reason="The evaluator did not return this item explicitly.",
                ),
            )
        )

    status = _clean_text(payload.get("status"))
    if status not in VALID_DIMENSION_STATUSES:
        if any(item.status == "fail" for item in items):
            status = "fail"
        elif any(item.status == "uncertain" for item in items):
            status = "uncertain"
        else:
            status = "pass"

    return DimensionResult(
        dimension=dimension,
        status=status,
        summary=_clean_text(payload.get("summary")),
        confidence=_clean_text(payload.get("confidence")) or "medium",
        items=items,
        compared_roles=compared_roles,
    )
