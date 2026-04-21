# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow>=12.2.0",
#     "requests>=2.33.1",
#     "ultralytics>=8.4.40",
# ]
# ///
import argparse
import json
import sys
from io import BytesIO
from typing import Any

import requests
from PIL import Image
from ultralytics import YOLO
from ultralytics.engine.results import Boxes

PERSON_CLASS_ID = 0


def fetch_image(url: str) -> Image.Image:
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    return Image.open(BytesIO(response.content)).convert("RGB")


def largest_person_bbox_xyxy(boxes: Boxes) -> list[float]:
    person_mask = boxes.cls == PERSON_CLASS_ID
    person_boxes = boxes.xyxy[person_mask]
    if len(person_boxes) == 0:
        msg = "No person detected in image"
        raise ValueError(msg)

    widths = person_boxes[:, 2] - person_boxes[:, 0]
    heights = person_boxes[:, 3] - person_boxes[:, 1]
    largest_index = (widths * heights).argmax()

    return person_boxes[largest_index].cpu().tolist()


def normalize_bbox(bbox: list[float], image: Image.Image) -> dict[str, float]:
    width, height = image.size
    x1, y1, x2, y2 = bbox

    return {
        "left": x1 / width,
        "top": y1 / height,
        "right": x2 / width,
        "bottom": y2 / height,
    }


def detect_largest_person_bbox(model: YOLO, image: Image.Image) -> dict[str, float]:
    detected = model.predict(image, save=False)
    bbox = largest_person_bbox_xyxy(detected[0].boxes)

    return normalize_bbox(bbox, image)


def compare_bboxes(
    reference_bbox: dict[str, float],
    output_bbox: dict[str, float],
    reference_aspect_ratio: float,
    output_aspect_ratio: float,
    threshold: float,
) -> dict[str, Any]:
    edge_diffs = {
        edge: abs(output_bbox[edge] - reference_bbox[edge])
        for edge in ("left", "top", "right", "bottom")
    }
    failed_edges = [edge for edge, diff in edge_diffs.items() if diff > threshold]
    aspect_ratio_diff = abs(output_aspect_ratio - reference_aspect_ratio)

    return {
        "passed": not failed_edges and aspect_ratio_diff <= threshold,
        "threshold": threshold,
        "reference_bbox": reference_bbox,
        "output_bbox": output_bbox,
        "edge_diffs": edge_diffs,
        "failed_edges": failed_edges,
        "reference_aspect_ratio": reference_aspect_ratio,
        "output_aspect_ratio": output_aspect_ratio,
        "aspect_ratio_diff": aspect_ratio_diff,
        "aspect_ratio_passed": aspect_ratio_diff <= threshold,
    }


def verify_composition(
    reference: str,
    output: str,
    threshold: float,
) -> dict[str, Any]:
    reference_image = fetch_image(reference)
    output_image = fetch_image(output)

    model = YOLO("yolo26n.pt")
    reference_bbox = detect_largest_person_bbox(model, reference_image)
    output_bbox = detect_largest_person_bbox(model, output_image)
    reference_width, reference_height = reference_image.size
    output_width, output_height = output_image.size
    reference_aspect_ratio = reference_width / reference_height
    output_aspect_ratio = output_width / output_height

    return compare_bboxes(
        reference_bbox,
        output_bbox,
        reference_aspect_ratio,
        output_aspect_ratio,
        threshold,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify subject composition by comparing normalized person bbox edges."
    )
    parser.add_argument("--result", required=True)
    parser.add_argument("--background-reference", required=True)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.1,
        help="Maximum allowed normalized edge-position and aspect-ratio difference.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    result = verify_composition(args.background_reference, args.result, args.threshold)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
