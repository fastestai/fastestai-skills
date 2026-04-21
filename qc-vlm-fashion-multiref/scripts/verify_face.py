# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "deepface>=0.0.99",
#     "keras>=3.12.1",
#     "numpy>=2.2.6",
#     "pillow>=12.2.0",
#     "requests>=2.33.1",
#     "tf-keras>=2.21.0",
# ]
# ///
import argparse
import sys
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import numpy as np
import requests
from deepface import DeepFace
from PIL import Image

MAX_FACE_INPUT_SIDE = 1200


def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"}


def open_image(source: str) -> Image.Image:
    if is_url(source):
        response = requests.get(source, timeout=60)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))

    return Image.open(source)


def load_resized_image(source: str) -> np.ndarray:
    image = open_image(source).convert("RGB")
    image.thumbnail(
        (MAX_FACE_INPUT_SIDE, MAX_FACE_INPUT_SIDE),
        Image.Resampling.LANCZOS,
    )

    return np.array(image)


def filter_main_face(faces: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = [x["facial_area"]["w"] * x["facial_area"]["h"] for x in faces]
    max_size = max(sizes)

    return faces[sizes.index(max_size)]


def verify_face(reference: str, output: str) -> dict[str, Any]:
    reference_image = load_resized_image(reference)
    output_image = load_resized_image(output)

    try:
        reference_face = DeepFace.extract_faces(
            reference_image, detector_backend="mtcnn"
        )
    except ValueError as error:
        msg = f"Failed to extract face from reference image: {error}"
        raise RuntimeError(msg) from error

    if reference_face is None:
        msg = "No face extracted from reference image"
        raise RuntimeError(msg)

    reference_face = filter_main_face(reference_face)

    try:
        output_face = DeepFace.extract_faces(output_image, detector_backend="mtcnn")
    except ValueError as error:
        msg = f"Failed to extract face from output image: {error}"
        raise RuntimeError(msg) from error

    if output_face is None:
        msg = "No face extracted from output image"
        raise RuntimeError(msg)

    output_face = filter_main_face(output_face)

    return DeepFace.verify(
        reference_face["face"],
        output_face["face"],
        detector_backend="skip",
        enforce_detection=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run face verification QC for generated fashion images."
    )
    parser.add_argument("--result")
    parser.add_argument("--model-reference")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    result = verify_face(args.result, args.model_reference)
    sys.stdout.write(f"{result}\n")


if __name__ == "__main__":
    main()
