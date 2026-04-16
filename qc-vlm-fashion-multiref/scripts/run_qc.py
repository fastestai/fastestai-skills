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
REQUIRED_ROLES = {"result", "model_reference", "garment_reference"}
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


def validate_required_roles(role_to_source: dict[str, str]) -> None:
    missing = sorted(REQUIRED_ROLES - set(role_to_source))
    if missing:
        raise ValueError(f"Missing required roles: {', '.join(missing)}")


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
    validate_required_roles(role_to_source)

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


def build_coarse_message(inputs: NormalizedInputs) -> tuple[list[str], str]:
    ordered_roles = [
        "result",
        "model_reference",
        "garment_reference",
        "pose_reference",
        "background_reference",
    ]
    image_urls: list[str] = []
    lines = [
        "Evaluate the following images as a coarse QC gate for a generated fashion image.",
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


def run() -> int:
    args = parse_args()
    role_to_source = build_role_to_source(args)
    inputs = normalize_inputs(role_to_source, args.upload_prefix)

    client = WFMultimodalClient(
        mcp_url=args.mcp_url or WFMultimodalClient().mcp_url,
        default_model=args.model,
        wf_binary=args.wf_binary,
    )

    coarse_images, coarse_message = build_coarse_message(inputs)
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
            },
        )
    else:
        skip_detailed = coarse.status == "fail" and not args.force_detailed
        for dimension, spec in DIMENSION_SPECS.items():
            missing_roles = [
                role for role in spec["roles"] if role not in inputs.role_to_url
            ]
            if missing_roles:
                payload = missing_dimension_result(dimension)
            elif skip_detailed:
                payload = skipped_dimension_result(dimension)
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
