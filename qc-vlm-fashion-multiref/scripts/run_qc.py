from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# ruff: noqa: E402
from aggregate import build_report
from render_report import render_markdown
from schema import (
    InputImage,
    NormalizedInputs,
    build_coarse_result,
    build_dimension_result,
    utc_timestamp,
)
from vlm_client import DEFAULT_MODEL, WFMultimodalClient


ROLE_NAMES = [
    "result",
    "model_reference",
    "garment_reference",
    "pose_reference",
    "background_reference",
]
PROMPT_DIR = SCRIPT_DIR.parent / "references"
COS_UPLOAD_SCRIPT = (
    SCRIPT_DIR.parent.parent / "cos-upload" / "scripts" / "cos_upload.py"
)

DIMENSION_SPECS = {
    "identity": {
        "prompt_file": "prompt-identity.md",
        "roles": ["model_reference", "result"],
        "items": [
            "model_face",
            "makeup_hair",
            "body_skin_tone",
            "skin_evenness",
        ],
    },
    "garment": {
        "prompt_file": "prompt-garment.md",
        "roles": ["garment_reference", "result"],
        "items": [
            "garment_shape",
            "pattern_details",
            "material_texture",
            "transparency_distribution",
            "hem_length_and_edge",
            "garment_color",
            "wearing_naturalness",
        ],
    },
    "pose": {
        "prompt_file": "prompt-pose.md",
        "roles": ["pose_reference", "result"],
        "items": [
            "overall_pose",
            "hand_head_details",
            "framing_proportion",
        ],
    },
    "background": {
        "prompt_file": "prompt-background.md",
        "roles": ["background_reference", "result"],
        "items": [
            "background_content",
            "background_tone",
            "background_texture",
            "background_lighting",
        ],
    },
    "fusion": {
        "prompt_file": "prompt-fusion.md",
        "roles": ["background_reference", "result"],
        "items": [
            "edge_blending",
            "lighting_consistency",
        ],
    },
    "quality": {
        "prompt_file": "prompt-quality.md",
        "roles": ["result"],
        "items": [
            "base_image_quality",
        ],
    },
}
CHECK_NAMES = list(DIMENSION_SPECS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multi-reference VLM QC for generated fashion images."
    )
    parser.add_argument("--input-json", help="Inline JSON string or path to a JSON file.")
    parser.add_argument("--result")
    parser.add_argument("--model-reference")
    parser.add_argument("--garment-reference")
    parser.add_argument(
        "--reference",
        help="Shared reference image that should be treated as both pose_reference and background_reference.",
    )
    parser.add_argument("--pose-reference")
    parser.add_argument("--background-reference")
    parser.add_argument(
        "--checks",
        help=(
            "Comma-separated checks to run. "
            f"Available: {', '.join(CHECK_NAMES)}. "
            "If omitted, the script auto-selects every check supported by the provided inputs."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--mcp-url")
    parser.add_argument("--wf-binary", default="wf")
    parser.add_argument("--upload-prefix", default="qc-vlm-fashion-multiref")
    parser.add_argument("--force-detailed", action="store_true")
    parser.add_argument("--coarse-only", action="store_true")
    parser.add_argument(
        "--stdout-format",
        choices=["markdown", "json", "both"],
        default="markdown",
    )
    parser.add_argument("--output", help="Deprecated alias for --output-json.")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    return parser.parse_args()


def load_json_input(raw: str) -> dict[str, Any]:
    path = Path(raw)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(raw)


def build_role_to_source(args: argparse.Namespace) -> dict[str, str]:
    if args.input_json:
        payload = load_json_input(args.input_json)
        images = payload["images"] if isinstance(payload, dict) and "images" in payload else payload
        role_to_source: dict[str, str] = {}
        for image in images:
            source = image["source"]
            roles = list(image["roles"])
            for role in roles:
                if role in role_to_source and role_to_source[role] != source:
                    raise ValueError(f"Role {role} is mapped to more than one source.")
                role_to_source[role] = source
        return role_to_source

    role_to_source = {}
    if args.result:
        role_to_source["result"] = args.result
    if args.model_reference:
        role_to_source["model_reference"] = args.model_reference
    if args.garment_reference:
        role_to_source["garment_reference"] = args.garment_reference
    if args.reference:
        role_to_source.setdefault("pose_reference", args.reference)
        role_to_source.setdefault("background_reference", args.reference)
    if args.pose_reference:
        role_to_source["pose_reference"] = args.pose_reference
    if args.background_reference:
        role_to_source["background_reference"] = args.background_reference
    return role_to_source


def parse_requested_checks(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    checks = [item.strip() for item in raw.split(",") if item.strip()]
    if not checks:
        raise ValueError("`--checks` was provided but no check names were found.")

    unknown = [item for item in checks if item not in DIMENSION_SPECS]
    if unknown:
        raise ValueError(
            f"Unknown checks: {', '.join(unknown)}. "
            f"Available checks: {', '.join(CHECK_NAMES)}"
        )

    unique_checks: list[str] = []
    for item in checks:
        if item not in unique_checks:
            unique_checks.append(item)
    return unique_checks


def resolve_selected_checks(
    role_to_source: dict[str, str],
    requested_checks: list[str] | None,
) -> tuple[list[str], str]:
    available_roles = set(role_to_source)

    if requested_checks is not None:
        required_roles = {
            role
            for check in requested_checks
            for role in DIMENSION_SPECS[check]["roles"]
        }
        missing_roles = sorted(required_roles - available_roles)
        if missing_roles:
            raise ValueError(
                "The selected checks need more inputs. Missing roles: "
                f"{', '.join(missing_roles)}"
            )
        return requested_checks, "explicit"

    auto_checks = [
        check
        for check in CHECK_NAMES
        if all(role in available_roles for role in DIMENSION_SPECS[check]["roles"])
    ]
    if not auto_checks:
        raise ValueError(
            "No checks can run with the provided inputs. "
            f"Available checks are: {', '.join(CHECK_NAMES)}"
        )
    return auto_checks, "auto"


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def ensure_public_url(source: str, upload_prefix: str, role: str) -> tuple[str, bool]:
    if is_url(source):
        return source, False

    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Image source not found: {source}")
    if not COS_UPLOAD_SCRIPT.exists():
        raise FileNotFoundError(
            f"COS upload script not found: {COS_UPLOAD_SCRIPT}"
        )

    scoped_prefix = f"{upload_prefix}/{role}/"
    completed = subprocess.run(
        [sys.executable, str(COS_UPLOAD_SCRIPT), str(source_path), scoped_prefix],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "COS upload failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed.stdout.strip(), True


def normalize_inputs(role_to_source: dict[str, str], upload_prefix: str) -> NormalizedInputs:
    role_to_url: dict[str, str] = {}
    source_cache: dict[str, tuple[str, bool]] = {}
    images_by_source: dict[str, InputImage] = {}

    for role in ROLE_NAMES:
        source = role_to_source.get(role)
        if not source:
            continue
        if source not in source_cache:
            source_cache[source] = ensure_public_url(source, upload_prefix, role)
        resolved_url, uploaded = source_cache[source]
        role_to_url[role] = resolved_url
        if source not in images_by_source:
            images_by_source[source] = InputImage(
                source=source,
                roles=[role],
                resolved_url=resolved_url,
                uploaded=uploaded,
            )
        else:
            images_by_source[source].roles.append(role)

    return NormalizedInputs(
        images=list(images_by_source.values()),
        role_to_source=role_to_source,
        role_to_url=role_to_url,
    )


def load_prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


def coarse_schema() -> dict[str, Any]:
    return {
        "status": "pass",
        "summary": "Short coarse summary.",
        "obvious_failures": ["List major visible issues only."],
        "suspect_dimensions": ["identity", "garment"],
    }


def dimension_schema(dimension: str, item_names: list[str]) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "status": "pass",
        "summary": "Short summary for this dimension.",
        "confidence": "high",
        "items": [
            {
                "name": item_name,
                "status": "pass",
                "reason": "Short evidence-based reason.",
            }
            for item_name in item_names
        ],
    }


def garment_fingerprint_schema() -> dict[str, Any]:
    return {
        "silhouette_and_structure": "Precise description of silhouette, neckline, upper structure, and body fit.",
        "pattern_and_surface_details": "Visible glitter, seams, ruching, pleats, or other construction details.",
        "material_and_sheen": "Fabric weight, sheen type, surface grain, stretch, and drape behavior.",
        "transparency_map": "Which garment regions are opaque, semi-sheer, or sheer.",
        "hem_length_and_edge": "Visible length, hem edge type, lower-layer behavior, and pooling or no pooling.",
        "color_profile": "Main color and tonal behavior.",
    }


def build_coarse_message(
    selected_checks: list[str],
    inputs: NormalizedInputs,
) -> tuple[list[str], str]:
    relevant_roles = {"result"}
    for check in selected_checks:
        relevant_roles.update(DIMENSION_SPECS[check]["roles"])

    ordered_roles = [role for role in ROLE_NAMES if role in relevant_roles]
    image_urls: list[str] = []
    lines = [
        "Evaluate the following images as a quick first-pass QC check.",
        f"Only judge these checks: {', '.join(selected_checks)}.",
        "Image order and roles:",
    ]
    seen_urls: set[str] = set()
    counter = 1
    for role in ordered_roles:
        url = inputs.role_to_url.get(role)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        image_urls.append(url)
        same_source_roles = [
            current_role
            for current_role, current_url in inputs.role_to_url.items()
            if current_url == url
        ]
        role_label = ", ".join(same_source_roles)
        lines.append(f"{counter}. {role_label}")
        counter += 1
    lines.append("Return JSON only.")
    return image_urls, "\n".join(lines)


def build_dimension_message(dimension: str, inputs: NormalizedInputs) -> tuple[list[str], str]:
    spec = DIMENSION_SPECS[dimension]
    image_urls: list[str] = []
    lines = [
        f"Evaluate only the {dimension} dimension.",
        "Image order and roles:",
    ]
    for index, role in enumerate(spec["roles"], start=1):
        url = inputs.role_to_url.get(role)
        if not url:
            continue
        image_urls.append(url)
        lines.append(f"{index}. {role}")
    lines.append("Return JSON only.")
    return image_urls, "\n".join(lines)


def build_garment_reference_message(inputs: NormalizedInputs) -> tuple[list[str], str]:
    garment_url = inputs.role_to_url["garment_reference"]
    lines = [
        "Analyze only the garment reference image and extract a structured garment fingerprint.",
        "Focus especially on transparency placement, lining placement, hem length, and lower edge behavior.",
        "Image order and roles:",
        "1. garment_reference",
        "Return JSON only.",
    ]
    return [garment_url], "\n".join(lines)


def build_garment_verification_message(
    inputs: NormalizedInputs,
    garment_fingerprint: dict[str, Any],
) -> tuple[list[str], str]:
    garment_url = inputs.role_to_url["garment_reference"]
    result_url = inputs.role_to_url["result"]
    lines = [
        "Evaluate only garment consistency using the garment fingerprint below as the main checklist.",
        "If the generated garment changes transparency placement, lining placement, or hem length in a meaningful way, the related item must not be pass.",
        "Garment fingerprint:",
        json.dumps(garment_fingerprint, ensure_ascii=False, indent=2),
        "Image order and roles:",
        "1. garment_reference",
        "2. result",
        "Return JSON only.",
    ]
    return [garment_url, result_url], "\n".join(lines)


def build_garment_mismatch_message(
    inputs: NormalizedInputs,
    garment_fingerprint: dict[str, Any],
) -> tuple[list[str], str]:
    garment_url = inputs.role_to_url["garment_reference"]
    result_url = inputs.role_to_url["result"]
    lines = [
        "Find meaningful garment mismatches using the garment fingerprint below as the checklist.",
        "Focus on local mismatches even if the overall garment looks similar.",
        "If transparency placement, lining placement, or hem length clearly changed, the related item must not be pass.",
        "Garment fingerprint:",
        json.dumps(garment_fingerprint, ensure_ascii=False, indent=2),
        "Image order and roles:",
        "1. garment_reference",
        "2. result",
        "Return JSON only.",
    ]
    return [garment_url, result_url], "\n".join(lines)


def invoke_with_retry(
    client: WFMultimodalClient,
    prompt: str,
    message: str,
    images: list[str],
    response_schema: dict[str, Any],
) -> Any:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return client.invoke(
                prompt=prompt,
                message=message,
                images=images,
                response_schema=response_schema,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    assert last_error is not None
    raise last_error


def missing_dimension_result(dimension: str) -> dict[str, Any]:
    items = [
        {
            "name": item_name,
            "status": "uncertain",
            "reason": "Missing required image input for this evaluator.",
        }
        for item_name in DIMENSION_SPECS[dimension]["items"]
    ]
    return {
        "dimension": dimension,
        "status": "missing_input",
        "summary": "Required role image is missing for this dimension.",
        "confidence": "low",
        "items": items,
    }


def skipped_dimension_result(dimension: str) -> dict[str, Any]:
    items = [
        {
            "name": item_name,
            "status": "uncertain",
            "reason": "Detailed evaluation was skipped after coarse hard fail.",
        }
        for item_name in DIMENSION_SPECS[dimension]["items"]
    ]
    return {
        "dimension": dimension,
        "status": "skipped_after_coarse",
        "summary": "Skipped because coarse gate already found an obvious failure.",
        "confidence": "low",
        "items": items,
    }


def merge_garment_payloads(
    verify_payload: dict[str, Any],
    mismatch_payload: dict[str, Any],
    item_names: list[str],
) -> dict[str, Any]:
    verify_items = {
        item.get("name"): item
        for item in verify_payload.get("items") or []
        if isinstance(item, dict) and item.get("name")
    }
    mismatch_items = {
        item.get("name"): item
        for item in mismatch_payload.get("items") or []
        if isinstance(item, dict) and item.get("name")
    }

    merged_items: list[dict[str, Any]] = []
    for item_name in item_names:
        verify_item = verify_items.get(item_name, {})
        mismatch_item = mismatch_items.get(item_name, {})
        verify_status = str(verify_item.get("status", "uncertain")).strip() or "uncertain"
        mismatch_status = str(mismatch_item.get("status", "uncertain")).strip() or "uncertain"
        verify_reason = _short_reason(verify_item.get("reason", ""))
        mismatch_reason = _short_reason(mismatch_item.get("reason", ""))

        if mismatch_status == "fail":
            merged_status = "fail"
            merged_reason = mismatch_reason or verify_reason or "A meaningful mismatch was found."
        elif verify_status == "fail":
            merged_status = "fail"
            merged_reason = verify_reason or mismatch_reason or "A meaningful mismatch was found."
        elif mismatch_status == "uncertain" or verify_status == "uncertain":
            merged_status = "uncertain"
            merged_reason = mismatch_reason or verify_reason or "The evidence was mixed."
        else:
            merged_status = "pass"
            merged_reason = verify_reason or mismatch_reason or "No meaningful mismatch was found."

        merged_items.append(
            {
                "name": item_name,
                "status": merged_status,
                "reason": merged_reason,
            }
        )

    statuses = [item["status"] for item in merged_items]
    if "fail" in statuses:
        merged_status = "fail"
    elif "uncertain" in statuses:
        merged_status = "uncertain"
    else:
        merged_status = "pass"

    summary = _merge_garment_summary(
        verify_payload.get("summary", ""),
        mismatch_payload.get("summary", ""),
        merged_status,
    )

    return {
        "dimension": "garment",
        "status": merged_status,
        "summary": summary or "Combined garment verification result.",
        "confidence": "high" if merged_status != "uncertain" else "medium",
        "items": merged_items,
    }


def _short_reason(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= 180:
        return text
    sentence_endings = [". ", "; ", " However", " But "]
    for token in sentence_endings:
        index = text.find(token)
        if index > 40:
            return text[: index + (1 if token in {". ", "; "} else 0)].strip()
    return text[:177].rstrip() + "..."


def _merge_garment_summary(
    verify_summary: Any,
    mismatch_summary: Any,
    merged_status: str,
) -> str:
    verify_text = _short_reason(verify_summary)
    mismatch_text = _short_reason(mismatch_summary)
    if merged_status == "fail":
        return mismatch_text or verify_text
    if merged_status == "uncertain":
        return mismatch_text or verify_text or "The garment evidence was mixed."
    return verify_text or mismatch_text or "The garment matches the reference."


def run() -> int:
    args = parse_args()
    role_to_source = build_role_to_source(args)
    requested_checks = parse_requested_checks(args.checks)
    selected_checks, selection_mode = resolve_selected_checks(
        role_to_source, requested_checks
    )
    inputs = normalize_inputs(role_to_source, args.upload_prefix)

    client = WFMultimodalClient(
        mcp_url=args.mcp_url or WFMultimodalClient().mcp_url,
        default_model=args.model,
        wf_binary=args.wf_binary,
    )
    intermediate_artifacts: dict[str, Any] = {}

    coarse_images, coarse_message = build_coarse_message(selected_checks, inputs)
    coarse_payload = invoke_with_retry(
        client=client,
        prompt=load_prompt("prompt-coarse.md"),
        message=coarse_message,
        images=coarse_images,
        response_schema=coarse_schema(),
    )
    if not isinstance(coarse_payload, dict):
        coarse_payload = {"status": "uncertain", "summary": f"Unexpected coarse payload: {coarse_payload}"}
    coarse = build_coarse_result(coarse_payload)

    dimensions = []
    if args.coarse_only:
        report = build_report(
            coarse=coarse,
            dimensions=dimensions,
            inputs=inputs,
            metadata={
                "generated_at": utc_timestamp(),
                "model": args.model,
                "mode": "coarse_only",
                "selected_checks": selected_checks,
                "check_selection_mode": selection_mode,
            },
        )
    else:
        skip_detailed = coarse.status == "fail" and not args.force_detailed
        for dimension in selected_checks:
            spec = DIMENSION_SPECS[dimension]
            missing_roles = [
                role for role in spec["roles"] if role not in inputs.role_to_url
            ]
            if missing_roles:
                payload = missing_dimension_result(dimension)
            elif skip_detailed:
                payload = skipped_dimension_result(dimension)
            else:
                if dimension == "garment":
                    garment_reference_payload = invoke_with_retry(
                        client=client,
                        prompt=load_prompt("prompt-garment-fingerprint.md"),
                        message=build_garment_reference_message(inputs)[1],
                        images=build_garment_reference_message(inputs)[0],
                        response_schema=garment_fingerprint_schema(),
                    )
                    if not isinstance(garment_reference_payload, dict):
                        garment_reference_payload = {
                            "raw_result": garment_reference_payload
                        }
                    intermediate_artifacts["garment_reference_fingerprint"] = (
                        garment_reference_payload
                    )
                    prompt = load_prompt(spec["prompt_file"])
                    images, message = build_garment_verification_message(
                        inputs, garment_reference_payload
                    )
                    verify_payload = invoke_with_retry(
                        client=client,
                        prompt=prompt,
                        message=message,
                        images=images,
                        response_schema=dimension_schema(dimension, spec["items"]),
                    )
                    mismatch_payload = invoke_with_retry(
                        client=client,
                        prompt=load_prompt("prompt-garment-mismatch.md"),
                        message=build_garment_mismatch_message(
                            inputs, garment_reference_payload
                        )[1],
                        images=build_garment_mismatch_message(
                            inputs, garment_reference_payload
                        )[0],
                        response_schema=dimension_schema(dimension, spec["items"]),
                    )
                    if not isinstance(verify_payload, dict):
                        verify_payload = {"raw_result": verify_payload}
                    if not isinstance(mismatch_payload, dict):
                        mismatch_payload = {"raw_result": mismatch_payload}
                    intermediate_artifacts["garment_verify_payload"] = verify_payload
                    intermediate_artifacts["garment_mismatch_payload"] = mismatch_payload
                    payload = merge_garment_payloads(
                        verify_payload, mismatch_payload, spec["items"]
                    )
                else:
                    prompt = load_prompt(spec["prompt_file"])
                    images, message = build_dimension_message(dimension, inputs)
                    payload = invoke_with_retry(
                        client=client,
                        prompt=prompt,
                        message=message,
                        images=images,
                        response_schema=dimension_schema(dimension, spec["items"]),
                    )
                if not isinstance(payload, dict):
                    payload = {
                        "dimension": dimension,
                        "status": "uncertain",
                        "summary": f"Unexpected evaluator payload: {payload}",
                        "confidence": "low",
                        "items": [],
                    }
            dimensions.append(
                build_dimension_result(
                    payload=payload,
                    dimension=dimension,
                    item_names=spec["items"],
                    compared_roles=spec["roles"],
                )
            )

        report = build_report(
            coarse=coarse,
            dimensions=dimensions,
            inputs=inputs,
            metadata={
                "generated_at": utc_timestamp(),
                "model": args.model,
                "mode": "coarse_plus_detailed",
                "force_detailed": args.force_detailed,
                "selected_checks": selected_checks,
                "check_selection_mode": selection_mode,
                "intermediate_artifacts": intermediate_artifacts,
            },
        )

    output = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    markdown = render_markdown(report.to_dict())

    output_json_path = args.output_json or args.output
    if output_json_path:
        Path(output_json_path).write_text(output + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(markdown, encoding="utf-8")

    if args.stdout_format == "json":
        print(output)
    elif args.stdout_format == "both":
        print(markdown.rstrip())
        print()
        print("```json")
        print(output)
        print("```")
    else:
        print(markdown.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
