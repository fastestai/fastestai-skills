"""
Standalone pose comparison tool.

Compares the main person's pose across two images using DWPose (YOLOX-L +
RTMPose-L) ONNX models, producing a visual comparison panel and numeric
similarity scores.

No local project imports — all dependencies (dwpose runtime, skeleton
drawing) are inlined.  Only requires: opencv-python, numpy, onnxruntime.

Usage:
  python pose_compare_standalone.py image_a.jpg image_b.jpg
  python pose_compare_standalone.py image_a.jpg image_b.jpg -o result.png
  python pose_compare_standalone.py image_a.jpg image_b.jpg --models-dir /path/to/dwpose

The --models-dir must contain:
  yolox_l.onnx          (YOLOX-L person detector)
  dw-ll_ucoco_384.onnx  (DWPose whole-body estimator)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort

# ---------------------------------------------------------------------------
# DWPose ONNX runtime (inlined from dwpose_runtime.py)
# ---------------------------------------------------------------------------

_DET_SESSION: ort.InferenceSession | None = None
_POSE_SESSION: ort.InferenceSession | None = None
_DET_MODEL_PATH: str = ""
_POSE_MODEL_PATH: str = ""

MODEL_FILES = {
    "yolox_l.onnx": {
        "url": "https://huggingface.co/yzd-v/DWPose/resolve/main/yolox_l.onnx?download=true",
        "sha256": "7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411",
    },
    "dw-ll_ucoco_384.onnx": {
        "url": "https://huggingface.co/yzd-v/DWPose/resolve/main/dw-ll_ucoco_384.onnx?download=true",
        "sha256": "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843",
    },
}


class PoseCompareError(RuntimeError):
    pass


def default_cache_dir() -> Path:
    cache_root = Path(
        os.environ.get("QC_VLM_FASHION_MULTIREF_CACHE_DIR")
        or os.environ.get("XDG_CACHE_HOME")
        or (Path.home() / ".cache")
    )
    return cache_root / "qc-vlm-fashion-multiref" / "dwpose"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_to_path(url: str, destination: Path, timeout_seconds: int = 600) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)


def ensure_model_file(
    filename: str,
    *,
    models_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 600,
) -> tuple[Path, str]:
    if filename not in MODEL_FILES:
        raise PoseCompareError(f"Unsupported DWPose model file: {filename}")

    candidates: list[Path] = []
    configured_dir = models_dir or os.environ.get("QC_VLM_FASHION_MULTIREF_DWPOSE_DIR")
    if configured_dir:
        candidates.append(Path(configured_dir).expanduser().resolve())
    cache_path = Path(cache_dir).expanduser().resolve() if cache_dir else default_cache_dir()
    if cache_path not in candidates:
        candidates.append(cache_path)

    model_info = MODEL_FILES[filename]
    expected_sha256 = model_info["sha256"]

    for directory in candidates:
        path = directory / filename
        if not path.exists():
            continue
        actual_sha256 = _sha256_file(path)
        if actual_sha256 == expected_sha256:
            return path, "local" if directory != cache_path else "cache"

    download_dir = cache_path
    download_dir.mkdir(parents=True, exist_ok=True)
    destination = download_dir / filename
    tmp_destination = destination.with_suffix(destination.suffix + ".tmp")
    try:
        if tmp_destination.exists():
            tmp_destination.unlink()
        _download_to_path(model_info["url"], tmp_destination, timeout_seconds)
        actual_sha256 = _sha256_file(tmp_destination)
        if actual_sha256 != expected_sha256:
            raise PoseCompareError(
                f"Downloaded {filename} but SHA256 mismatched. "
                f"Expected {expected_sha256}, got {actual_sha256}."
            )
        tmp_destination.replace(destination)
    except Exception as exc:
        if tmp_destination.exists():
            tmp_destination.unlink()
        raise PoseCompareError(
            f"Failed to download required DWPose model {filename}: {exc}"
        ) from exc

    return destination, "downloaded"


def resolve_models_dir(
    *,
    models_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    cache_path = Path(cache_dir).expanduser().resolve() if cache_dir else default_cache_dir()
    det_path, det_source = ensure_model_file(
        "yolox_l.onnx",
        models_dir=models_dir,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
    )
    pose_path, pose_source = ensure_model_file(
        "dw-ll_ucoco_384.onnx",
        models_dir=models_dir,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
    )
    resolved_dir = det_path.parent
    if pose_path.parent != resolved_dir:
        resolved_dir = cache_path
        resolved_dir.mkdir(parents=True, exist_ok=True)
        unified_det_path = resolved_dir / det_path.name
        unified_pose_path = resolved_dir / pose_path.name
        if det_path != unified_det_path:
            shutil.copy2(det_path, unified_det_path)
            det_path = unified_det_path
            det_source = "cache"
        if pose_path != unified_pose_path:
            shutil.copy2(pose_path, unified_pose_path)
            pose_path = unified_pose_path
            pose_source = "cache"
    return {
        "models_dir": resolved_dir,
        "det_model_path": det_path,
        "pose_model_path": pose_path,
        "det_model_source": det_source,
        "pose_model_source": pose_source,
    }


def _init_model_paths(models_dir: str) -> None:
    global _DET_MODEL_PATH, _POSE_MODEL_PATH, _DET_SESSION, _POSE_SESSION
    next_det_path = os.path.join(models_dir, "yolox_l.onnx")
    next_pose_path = os.path.join(models_dir, "dw-ll_ucoco_384.onnx")
    if next_det_path != _DET_MODEL_PATH:
        _DET_SESSION = None
    if next_pose_path != _POSE_MODEL_PATH:
        _POSE_SESSION = None
    _DET_MODEL_PATH = next_det_path
    _POSE_MODEL_PATH = next_pose_path


def _ort_providers() -> list[str]:
    available = set(ort.get_available_providers())
    providers: list[str] = []
    if "CUDAExecutionProvider" in available:
        providers.append("CUDAExecutionProvider")
    if "CoreMLExecutionProvider" in available:
        providers.append("CoreMLExecutionProvider")
    providers.append("CPUExecutionProvider")
    return providers


def _get_det_session() -> ort.InferenceSession:
    global _DET_SESSION
    if _DET_SESSION is None:
        _DET_SESSION = ort.InferenceSession(_DET_MODEL_PATH, providers=_ort_providers())
    return _DET_SESSION


def _get_pose_session() -> ort.InferenceSession:
    global _POSE_SESSION
    if _POSE_SESSION is None:
        _POSE_SESSION = ort.InferenceSession(
            _POSE_MODEL_PATH, providers=_ort_providers()
        )
    return _POSE_SESSION


def _det_preprocess(
    img: np.ndarray, input_size: tuple[int, int] = (640, 640)
) -> tuple[np.ndarray, float]:
    padded = np.ones((input_size[0], input_size[1], 3), dtype=np.uint8) * 114
    ratio = min(input_size[0] / img.shape[0], input_size[1] / img.shape[1])
    resized = cv2.resize(
        img,
        (int(img.shape[1] * ratio), int(img.shape[0] * ratio)),
        interpolation=cv2.INTER_LINEAR,
    ).astype(np.uint8)
    padded[: resized.shape[0], : resized.shape[1]] = resized
    padded = padded.transpose(2, 0, 1).astype(np.float32)
    return padded[None], ratio


def _det_postprocess(output: np.ndarray, img_size: tuple[int, int]) -> np.ndarray:
    grids, expanded_strides = [], []
    strides = [8, 16, 32]
    for stride in strides:
        h, w = img_size[0] // stride, img_size[1] // stride
        xv, yv = np.meshgrid(np.arange(w), np.arange(h))
        grids.append(np.stack((xv, yv), 2).reshape(1, -1, 2))
        expanded_strides.append(np.full((*grids[-1].shape[:2], 1), stride))
    grids = np.concatenate(grids, 1)
    expanded_strides = np.concatenate(expanded_strides, 1)
    output[..., :2] = (output[..., :2] + grids) * expanded_strides
    output[..., 2:4] = np.exp(output[..., 2:4]) * expanded_strides
    return output


def _nms(boxes: np.ndarray, scores: np.ndarray, thr: float) -> list[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        idx = order[0]
        keep.append(idx)
        xx1 = np.maximum(x1[idx], x1[order[1:]])
        yy1 = np.maximum(y1[idx], y1[order[1:]])
        xx2 = np.minimum(x2[idx], x2[order[1:]])
        yy2 = np.minimum(y2[idx], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        overlap = inter / (areas[idx] + areas[order[1:]] - inter)
        order = order[np.where(overlap <= thr)[0] + 1]
    return keep


def detect_persons_dwpose(img: np.ndarray) -> np.ndarray:
    session = _get_det_session()
    inp, ratio = _det_preprocess(img)
    output = session.run(None, {session.get_inputs()[0].name: inp})
    predictions = _det_postprocess(np.asarray(output[0]), (640, 640))[0]

    boxes = predictions[:, :4]
    scores = predictions[:, 4:5] * predictions[:, 5:]

    boxes_xyxy = np.empty_like(boxes)
    boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
    boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
    boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
    boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
    boxes_xyxy /= ratio

    cls_scores = scores[:, 0]
    valid = cls_scores > 0.3
    if not np.any(valid):
        return np.array([]).reshape(0, 4)
    valid_boxes = boxes_xyxy[valid]
    valid_scores = cls_scores[valid]
    keep = _nms(valid_boxes, valid_scores, 0.45)
    return valid_boxes[keep]


def _bbox_xyxy2cs(
    bbox: np.ndarray, padding: float = 1.25
) -> tuple[np.ndarray, np.ndarray]:
    x1, y1, x2, y2 = bbox
    center = np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float32)
    scale = np.array([(x2 - x1) * padding, (y2 - y1) * padding], dtype=np.float32)
    return center, scale


def _fix_aspect_ratio(scale: np.ndarray, aspect_ratio: float) -> np.ndarray:
    w, h = scale
    if w > h * aspect_ratio:
        return np.array([w, w / aspect_ratio], dtype=np.float32)
    return np.array([h * aspect_ratio, h], dtype=np.float32)


def _rotate_point(pt: np.ndarray, angle_rad: float) -> np.ndarray:
    sn, cs = np.sin(angle_rad), np.cos(angle_rad)
    return np.array(
        [cs * pt[0] - sn * pt[1], sn * pt[0] + cs * pt[1]], dtype=np.float32
    )


def _get_3rd_point(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    delta = a - b
    return b + np.array([-delta[1], delta[0]], dtype=np.float32)


def _get_warp_matrix(
    center: np.ndarray,
    scale: np.ndarray,
    rot: float,
    output_size: tuple[int, int],
    inv: bool = False,
) -> np.ndarray:
    shift = np.array([0.0, 0.0])
    src_w = scale[0]
    dst_w, dst_h = output_size
    rot_rad = np.deg2rad(rot)
    src_dir = _rotate_point(np.array([0.0, src_w * -0.5]), rot_rad)
    dst_dir = np.array([0.0, dst_w * -0.5])

    src = np.zeros((3, 2), dtype=np.float32)
    src[0] = center + scale * shift
    src[1] = center + src_dir + scale * shift
    src[2] = _get_3rd_point(src[0], src[1])

    dst = np.zeros((3, 2), dtype=np.float32)
    dst[0] = [dst_w * 0.5, dst_h * 0.5]
    dst[1] = np.array([dst_w * 0.5, dst_h * 0.5]) + dst_dir
    dst[2] = _get_3rd_point(dst[0], dst[1])

    if inv:
        return cv2.getAffineTransform(np.float32(dst), np.float32(src))
    return cv2.getAffineTransform(np.float32(src), np.float32(dst))


def _pose_preprocess(
    img: np.ndarray, bboxes: np.ndarray, input_size: tuple[int, int] = (288, 384)
) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    w, h = input_size
    out_imgs, out_centers, out_scales = [], [], []
    for bbox in bboxes:
        center, scale = _bbox_xyxy2cs(bbox, padding=1.25)
        scale = _fix_aspect_ratio(scale, w / h)
        warp_mat = _get_warp_matrix(center, scale, 0, (w, h))
        resized = cv2.warpAffine(img, warp_mat, (w, h), flags=cv2.INTER_LINEAR)
        mean = np.array([123.675, 116.28, 103.53])
        std = np.array([58.395, 57.12, 57.375])
        resized = (resized - mean) / std
        out_imgs.append(resized)
        out_centers.append(center)
        out_scales.append(scale)
    return out_imgs, out_centers, out_scales


def _simcc_decode(
    simcc_x: np.ndarray, simcc_y: np.ndarray, ratio: float = 2.0
) -> tuple[np.ndarray, np.ndarray]:
    num_samples, num_keypoints, _ = simcc_x.shape
    x_flat = simcc_x.reshape(num_samples * num_keypoints, -1)
    y_flat = simcc_y.reshape(num_samples * num_keypoints, -1)
    x_locs = np.argmax(x_flat, axis=1).astype(np.float32)
    y_locs = np.argmax(y_flat, axis=1).astype(np.float32)
    locs = np.stack((x_locs, y_locs), axis=-1)
    max_val_x = np.amax(x_flat, axis=1)
    max_val_y = np.amax(y_flat, axis=1)
    mask = max_val_x > max_val_y
    max_val_x[mask] = max_val_y[mask]
    vals = max_val_x
    locs[vals <= 0.0] = -1
    locs = locs.reshape(num_samples, num_keypoints, 2) / ratio
    vals = vals.reshape(num_samples, num_keypoints)
    return locs, vals


def estimate_poses(
    img: np.ndarray, bboxes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    if len(bboxes) == 0:
        return np.zeros((0, 133, 2)), np.zeros((0, 133))

    session = _get_pose_session()
    h_in, w_in = session.get_inputs()[0].shape[2:]
    model_input_size = (w_in, h_in)

    imgs, centers, scales = _pose_preprocess(img, bboxes, model_input_size)

    all_kpts, all_scores = [], []
    for idx, crop in enumerate(imgs):
        inp = crop.transpose(2, 0, 1).astype(np.float32)[None]
        outputs = session.run(None, {session.get_inputs()[0].name: inp})
        simcc_x, simcc_y = outputs
        kpts, scores = _simcc_decode(np.asarray(simcc_x), np.asarray(simcc_y))
        kpts = (
            kpts / np.array(model_input_size) * scales[idx]
            + centers[idx]
            - scales[idx] / 2
        )
        all_kpts.append(kpts[0])
        all_scores.append(scores[0])

    return np.array(all_kpts), np.array(all_scores)


# ---------------------------------------------------------------------------
# Skeleton drawing (inlined from body_mosaic_skeleton.py)
# ---------------------------------------------------------------------------

_OPENPOSE_LIMBS = [
    (17, 5),
    (17, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (17, 11),
    (17, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (0, 17),
    (0, 1),
    (1, 3),
    (0, 2),
    (2, 4),
]

_LIMB_COLORS = [
    (255, 0, 0),
    (255, 85, 0),
    (255, 170, 0),
    (255, 255, 0),
    (170, 255, 0),
    (85, 255, 0),
    (0, 255, 0),
    (0, 255, 85),
    (0, 255, 170),
    (0, 255, 255),
    (0, 170, 255),
    (0, 85, 255),
    (0, 0, 255),
    (85, 0, 255),
    (170, 0, 255),
    (255, 0, 255),
    (255, 0, 170),
    (255, 0, 85),
    (255, 0, 85),
]

_KPT_COLORS = [
    (255, 0, 0),
    (255, 85, 0),
    (255, 170, 0),
    (255, 255, 0),
    (170, 255, 0),
    (85, 255, 0),
    (0, 255, 0),
    (0, 255, 85),
    (0, 255, 170),
    (0, 255, 255),
    (0, 170, 255),
    (0, 85, 255),
    (0, 0, 255),
    (85, 0, 255),
    (170, 0, 255),
    (255, 0, 255),
    (255, 0, 170),
    (255, 0, 85),
]

_FOOT_SKELETON = [
    (15, 17),
    (15, 18),
    (15, 19),
    (16, 20),
    (16, 21),
    (16, 22),
]

_EPS = 0.01


def _draw_thick_limb(
    canvas: np.ndarray,
    pt1: tuple[int, int],
    pt2: tuple[int, int],
    color: tuple[int, ...],
    stickwidth: int,
) -> None:
    X = [pt1[1], pt2[1]]
    Y = [pt1[0], pt2[0]]
    mX, mY = np.mean(X), np.mean(Y)
    length = ((X[0] - X[1]) ** 2 + (Y[0] - Y[1]) ** 2) ** 0.5
    if length < 1:
        return
    angle = math.degrees(math.atan2(X[0] - X[1], Y[0] - Y[1]))
    polygon = cv2.ellipse2Poly(
        (int(mY), int(mX)), (int(length / 2), stickwidth), int(angle), 0, 360, 1
    )
    cv2.fillConvexPoly(canvas, polygon, color)


def _draw_body(
    canvas: np.ndarray,
    kpts: np.ndarray,
    scores: np.ndarray,
    thr: float,
    stickwidth: int,
    radius: int,
) -> None:
    neck_valid = scores[5] >= thr and scores[6] >= thr
    neck_pt = (kpts[5] + kpts[6]) / 2.0 if neck_valid else None
    neck_score = min(scores[5], scores[6]) if neck_valid else 0.0

    def _get_pt(idx: int) -> tuple[np.ndarray | None, float]:
        if idx == 17:
            return neck_pt, neck_score
        return kpts[idx], scores[idx]

    for idx, (i, j) in enumerate(_OPENPOSE_LIMBS):
        pt_i, sc_i = _get_pt(i)
        pt_j, sc_j = _get_pt(j)
        if pt_i is None or pt_j is None or sc_i < thr or sc_j < thr:
            continue
        color = _LIMB_COLORS[idx % len(_LIMB_COLORS)]
        _draw_thick_limb(
            canvas,
            (int(pt_i[0]), int(pt_i[1])),
            (int(pt_j[0]), int(pt_j[1])),
            color,
            stickwidth,
        )

    for i, j in _FOOT_SKELETON:
        if j >= len(scores):
            continue
        if scores[i] < thr or scores[j] < thr:
            continue
        _draw_thick_limb(
            canvas,
            (int(kpts[i][0]), int(kpts[i][1])),
            (int(kpts[j][0]), int(kpts[j][1])),
            (0, 255, 170),
            stickwidth,
        )

    for i in range(min(23, len(scores))):
        if scores[i] < thr:
            continue
        color = _KPT_COLORS[i % len(_KPT_COLORS)]
        cv2.circle(
            canvas, (int(kpts[i][0]), int(kpts[i][1])), radius, color, -1, cv2.LINE_AA
        )
    if neck_valid and neck_pt is not None:
        cv2.circle(
            canvas,
            (int(neck_pt[0]), int(neck_pt[1])),
            radius,
            (255, 128, 0),
            -1,
            cv2.LINE_AA,
        )


def draw_dwpose(
    canvas: np.ndarray,
    kpts: np.ndarray,
    scores: np.ndarray,
    thr: float = 0.3,
    stickwidth: int = 4,
    radius: int = 6,
    draw_face: bool = True,
    draw_hand: bool = True,
) -> None:
    _draw_body(canvas, kpts, scores, thr, stickwidth, radius)
    if draw_face:
        face_r = max(radius // 2, 2)
        for i in range(23, min(91, len(scores))):
            if scores[i] < thr:
                continue
            x, y = int(kpts[i][0]), int(kpts[i][1])
            if x > _EPS and y > _EPS:
                cv2.circle(canvas, (x, y), face_r, (255, 255, 255), -1, cv2.LINE_AA)
    if draw_hand:
        import matplotlib.colors as mcolors

        _hand_edges = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (0, 9), (9, 10), (10, 11), (11, 12),
            (0, 13), (13, 14), (14, 15), (15, 16),
            (0, 17), (17, 18), (18, 19), (19, 20),
        ]  # fmt: skip
        hand_thickness = max(stickwidth - 1, 2)
        hand_r = max(hand_thickness, 3)
        for offset in (91, 112):
            for ie, (a, b) in enumerate(_hand_edges):
                i, j = a + offset, b + offset
                if i >= len(scores) or j >= len(scores):
                    continue
                if scores[i] < thr or scores[j] < thr:
                    continue
                x1, y1 = int(kpts[i][0]), int(kpts[i][1])
                x2, y2 = int(kpts[j][0]), int(kpts[j][1])
                if x1 > _EPS and y1 > _EPS and x2 > _EPS and y2 > _EPS:
                    rgb = mcolors.hsv_to_rgb([ie / float(len(_hand_edges)), 1.0, 1.0])
                    color = (
                        int(rgb[0] * 255),
                        int(rgb[1] * 255),
                        int(rgb[2] * 255),
                    )
                    cv2.line(
                        canvas, (x1, y1), (x2, y2), color, hand_thickness, cv2.LINE_AA
                    )
            for i in range(offset, min(offset + 21, len(scores))):
                if scores[i] < thr:
                    continue
                x, y = int(kpts[i][0]), int(kpts[i][1])
                if x > _EPS and y > _EPS:
                    cv2.circle(canvas, (x, y), hand_r, (0, 0, 255), -1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Pose comparison constants
# ---------------------------------------------------------------------------

BODY_KEYPOINT_IDS = tuple(range(23))
TORSO_IDS = (5, 6, 11, 12)

POSITION_WEIGHTS = {
    0: 0.8,
    5: 1.1,
    6: 1.1,
    7: 1.2,
    8: 1.2,
    9: 1.2,
    10: 1.2,
    11: 1.3,
    12: 1.3,
    13: 1.3,
    14: 1.3,
    15: 1.2,
    16: 1.2,
    17: 0.6,
    18: 0.6,
    19: 0.5,
    20: 0.5,
    21: 0.5,
    22: 0.5,
}

ANGLE_SEGMENTS = (
    ((5, 7), 1.0),
    ((7, 9), 1.1),
    ((6, 8), 1.0),
    ((8, 10), 1.1),
    ((11, 13), 1.2),
    ((13, 15), 1.3),
    ((12, 14), 1.2),
    ((14, 16), 1.3),
    ((5, 11), 0.8),
    ((6, 12), 0.8),
    ((5, 6), 0.7),
    ((11, 12), 0.7),
)

SYMMETRY_PAIRS = (
    ((5, 7), (6, 8)),
    ((7, 9), (8, 10)),
    ((11, 13), (12, 14)),
    ((13, 15), (14, 16)),
)

BODY_LIMBS = (
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (15, 17),
    (15, 19),
    (15, 21),
    (16, 18),
    (16, 20),
    (16, 22),
)

POINT_COLOR_A = (70, 70, 235)
POINT_COLOR_B = (235, 140, 40)
TEXT_COLOR = (40, 40, 40)

MAJOR_LIMB_CHAINS = {
    "left_arm": {"joints": (5, 7, 9), "label": "left arm"},
    "right_arm": {"joints": (6, 8, 10), "label": "right arm"},
    "left_leg": {"joints": (11, 13, 15), "label": "left leg"},
    "right_leg": {"joints": (12, 14, 16), "label": "right leg"},
}

HAND_SPECS = {
    "left_hand": {"offset": 91, "wrist_idx": 9, "elbow_idx": 7, "label": "left hand"},
    "right_hand": {"offset": 112, "wrist_idx": 10, "elbow_idx": 8, "label": "right hand"},
}

HAND_FINGER_CHAINS = {
    "thumb": (1, 2, 3, 4),
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PoseDetection:
    image_path: Path
    image: np.ndarray
    bbox: np.ndarray
    keypoints: np.ndarray
    scores: np.ndarray


@dataclass
class PoseMetrics:
    overall_score: float
    position_similarity: float
    angle_similarity: float
    symmetry_similarity: float
    visibility_ratio: float
    matched_keypoints: int
    mean_position_distance: float
    mean_angle_difference: float


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the main person's pose across two images."
    )
    parser.add_argument("image_a", help="Path to the first image")
    parser.add_argument("image_b", help="Path to the second image")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path for the debug comparison image (omit to skip image generation)",
    )
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Preferred directory for yolox_l.onnx and dw-ll_ucoco_384.onnx.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Persistent cache directory for auto-downloaded DWPose ONNX models.",
    )
    parser.add_argument(
        "--score-thr",
        type=float,
        default=0.3,
        help="Minimum joint confidence to include in scoring and drawing",
    )
    parser.add_argument(
        "--panel-size",
        type=int,
        default=440,
        help="Square panel size for each section of the output image",
    )
    return parser.parse_args()


def load_image(path: str) -> np.ndarray:
    image = cv2.imread(path)
    if image is None:
        raise FileNotFoundError(f"Failed to read image: {path}")
    return image


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _ensure_local_image(
    source: str,
    temp_dir: Path,
    *,
    timeout_seconds: int = 120,
) -> Path:
    if _is_url(source):
        candidate_name = Path(source.split("?", 1)[0]).name or "image.jpg"
        destination = temp_dir / candidate_name
        _download_to_path(source, destination, timeout_seconds)
        return destination
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image source not found: {source}")
    return path


def detect_primary_pose(image_path: Path, image: np.ndarray) -> PoseDetection:
    bboxes = detect_persons_dwpose(image)
    if len(bboxes) == 0:
        raise ValueError(f"No person detected in {image_path}")

    areas = (bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])
    best_idx = int(np.argmax(areas))
    keypoints, scores = estimate_poses(image, bboxes[[best_idx]])
    return PoseDetection(
        image_path=image_path,
        image=image,
        bbox=bboxes[best_idx],
        keypoints=keypoints[0],
        scores=scores[0],
    )


# ---------------------------------------------------------------------------
# Normalization & scoring
# ---------------------------------------------------------------------------


def _torso_center(keypoints: np.ndarray, scores: np.ndarray, thr: float) -> np.ndarray:
    valid_points = [
        keypoints[idx] for idx in TORSO_IDS if idx < len(scores) and scores[idx] >= thr
    ]
    if valid_points:
        return np.mean(valid_points, axis=0)

    body_points = [
        keypoints[idx]
        for idx in BODY_KEYPOINT_IDS
        if idx < len(scores) and scores[idx] >= thr
    ]
    if not body_points:
        raise ValueError("No confident body keypoints available for normalization")
    return np.mean(body_points, axis=0)


def _normalization_scale(
    keypoints: np.ndarray, scores: np.ndarray, thr: float, center: np.ndarray
) -> float:
    shoulder_points = [
        keypoints[idx] for idx in (5, 6) if idx < len(scores) and scores[idx] >= thr
    ]
    hip_points = [
        keypoints[idx] for idx in (11, 12) if idx < len(scores) and scores[idx] >= thr
    ]
    if shoulder_points and hip_points:
        shoulder_center = np.mean(shoulder_points, axis=0)
        hip_center = np.mean(hip_points, axis=0)
        torso_length = float(np.linalg.norm(shoulder_center - hip_center))
        if torso_length > 1e-6:
            return torso_length

    body_points = np.array(
        [
            keypoints[idx]
            for idx in BODY_KEYPOINT_IDS
            if idx < len(scores) and scores[idx] >= thr
        ],
        dtype=np.float32,
    )
    if len(body_points) >= 2:
        extent = np.max(body_points, axis=0) - np.min(body_points, axis=0)
        bbox_diag = float(np.linalg.norm(extent))
        if bbox_diag > 1e-6:
            return bbox_diag

    distances = np.linalg.norm(body_points - center, axis=1) if len(body_points) else []
    if len(distances):
        max_distance = float(np.max(distances))
        if max_distance > 1e-6:
            return max_distance * 2.0

    raise ValueError("Failed to compute a stable normalization scale")


def normalize_pose(
    keypoints: np.ndarray, scores: np.ndarray, thr: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    center = _torso_center(keypoints, scores, thr)
    scale = _normalization_scale(keypoints, scores, thr, center)
    normalized = (keypoints[:, :2] - center[None, :]) / scale
    valid = scores >= thr
    return normalized, valid, center, scale


def _segment_angle(points: np.ndarray, start: int, end: int) -> float:
    vec = points[end] - points[start]
    return math.degrees(math.atan2(float(vec[1]), float(vec[0])))


def _angle_difference(angle_a: float, angle_b: float) -> float:
    diff = abs(angle_a - angle_b) % 360.0
    return min(diff, 360.0 - diff)


def _procrustes_align(
    pts_a: np.ndarray, pts_b: np.ndarray, shared_ids: list[int]
) -> np.ndarray:
    a = np.array([pts_a[i] for i in shared_ids], dtype=np.float64)
    b = np.array([pts_b[i] for i in shared_ids], dtype=np.float64)
    centroid_a = a.mean(axis=0)
    centroid_b = b.mean(axis=0)
    a_c = a - centroid_a
    b_c = b - centroid_b
    H = a_c.T @ b_c
    U, _, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    S = np.diag([1.0, 1.0 if d >= 0 else -1.0])
    R = Vt.T @ S @ U.T
    aligned = (pts_a - centroid_a) @ R.T + centroid_b
    return aligned.astype(np.float32)


def score_pose_similarity(
    pose_a: PoseDetection, pose_b: PoseDetection, thr: float
) -> tuple[PoseMetrics, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    norm_a, valid_a, _, _ = normalize_pose(pose_a.keypoints, pose_a.scores, thr)
    norm_b, valid_b, _, _ = normalize_pose(pose_b.keypoints, pose_b.scores, thr)

    shared_ids = [idx for idx in BODY_KEYPOINT_IDS if valid_a[idx] and valid_b[idx]]
    if not shared_ids:
        raise ValueError("The two images do not share any confident body keypoints")

    aligned_a = _procrustes_align(norm_a, norm_b, shared_ids)

    pos_diffs: list[float] = []
    pos_weights: list[float] = []
    for idx in shared_ids:
        weight = POSITION_WEIGHTS.get(idx, 1.0)
        diff = float(np.linalg.norm(aligned_a[idx] - norm_b[idx]))
        pos_diffs.append(diff)
        pos_weights.append(weight)

    mean_position_distance = float(
        np.average(np.array(pos_diffs), weights=np.array(pos_weights))
    )
    position_similarity = math.exp(-mean_position_distance / 0.20)

    angle_diffs: list[float] = []
    angle_weights: list[float] = []
    for (start, end), weight in ANGLE_SEGMENTS:
        if not (valid_a[start] and valid_a[end] and valid_b[start] and valid_b[end]):
            continue
        angle_a = _segment_angle(aligned_a, start, end)
        angle_b = _segment_angle(norm_b, start, end)
        angle_diffs.append(_angle_difference(angle_a, angle_b))
        angle_weights.append(weight)

    if angle_diffs:
        mean_angle_difference = float(
            np.average(np.array(angle_diffs), weights=np.array(angle_weights))
        )
        angle_similarity = math.exp(-mean_angle_difference / 50.0)
    else:
        mean_angle_difference = 180.0
        angle_similarity = 0.0

    sym_diffs: list[float] = []
    for seg_l, seg_r in SYMMETRY_PAIRS:
        l_ok = (
            valid_a[seg_l[0]]
            and valid_a[seg_l[1]]
            and valid_b[seg_l[0]]
            and valid_b[seg_l[1]]
        )
        r_ok = (
            valid_a[seg_r[0]]
            and valid_a[seg_r[1]]
            and valid_b[seg_r[0]]
            and valid_b[seg_r[1]]
        )
        if not (l_ok and r_ok):
            continue
        diff_a = _angle_difference(
            _segment_angle(aligned_a, seg_l[0], seg_l[1])
            - _segment_angle(aligned_a, seg_r[0], seg_r[1]),
            _segment_angle(norm_b, seg_l[0], seg_l[1])
            - _segment_angle(norm_b, seg_r[0], seg_r[1]),
        )
        sym_diffs.append(diff_a)
    symmetry_similarity = math.exp(-np.mean(sym_diffs) / 45.0) if sym_diffs else 1.0

    visibility_ratio = len(shared_ids) / len(BODY_KEYPOINT_IDS)

    raw = (
        0.50 * angle_similarity
        + 0.40 * position_similarity
        + 0.05 * visibility_ratio
        + 0.05 * symmetry_similarity
    )
    overall_score = 100.0 / (1.0 + math.exp(-12.0 * (raw - 0.5)))

    metrics = PoseMetrics(
        overall_score=overall_score,
        position_similarity=position_similarity,
        angle_similarity=angle_similarity,
        symmetry_similarity=symmetry_similarity,
        visibility_ratio=visibility_ratio,
        matched_keypoints=len(shared_ids),
        mean_position_distance=mean_position_distance,
        mean_angle_difference=mean_angle_difference,
    )
    return metrics, norm_a, valid_a, norm_b, valid_b


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


def _fit_image_to_panel(
    image: np.ndarray, panel_size: int, background: tuple[int, int, int]
) -> tuple[np.ndarray, float, tuple[int, int]]:
    panel = np.full((panel_size, panel_size, 3), background, dtype=np.uint8)
    height, width = image.shape[:2]
    scale = min(panel_size / width, panel_size / height)
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    resized = cv2.resize(
        image, (resized_width, resized_height), interpolation=cv2.INTER_AREA
    )
    offset_x = (panel_size - resized_width) // 2
    offset_y = (panel_size - resized_height) // 2
    panel[offset_y : offset_y + resized_height, offset_x : offset_x + resized_width] = (
        resized
    )
    return panel, scale, (offset_x, offset_y)


def _draw_bbox(
    panel: np.ndarray,
    bbox: np.ndarray,
    scale: float,
    offset: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = (bbox * scale).astype(int)
    offset_x, offset_y = offset
    cv2.rectangle(
        panel,
        (x1 + offset_x, y1 + offset_y),
        (x2 + offset_x, y2 + offset_y),
        color,
        2,
        cv2.LINE_AA,
    )


def _draw_title(panel: np.ndarray, title: str, subtitle: str = "") -> None:
    cv2.putText(
        panel,
        title,
        (18, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        TEXT_COLOR,
        2,
        cv2.LINE_AA,
    )
    if subtitle:
        cv2.putText(
            panel,
            subtitle,
            (18, 54),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (90, 90, 90),
            1,
            cv2.LINE_AA,
        )


def make_pose_panel(
    pose: PoseDetection,
    panel_size: int,
    score_thr: float,
    label: str,
) -> np.ndarray:
    panel, scale, offset = _fit_image_to_panel(pose.image, panel_size, (248, 248, 248))
    scaled_kpts = pose.keypoints.copy()
    scaled_kpts[:, 0] = scaled_kpts[:, 0] * scale + offset[0]
    scaled_kpts[:, 1] = scaled_kpts[:, 1] * scale + offset[1]
    draw_dwpose(
        panel,
        scaled_kpts,
        pose.scores,
        thr=score_thr,
        stickwidth=max(panel_size // 120, 3),
        radius=max(panel_size // 80, 4),
        draw_face=False,
        draw_hand=False,
    )
    _draw_bbox(panel, pose.bbox, scale, offset, (40, 180, 70))
    _draw_title(panel, label, pose.image_path.name)
    return panel


def _draw_overlay_grid(panel: np.ndarray) -> None:
    step = panel.shape[0] // 8
    for idx in range(step, panel.shape[0], step):
        cv2.line(
            panel, (idx, 0), (idx, panel.shape[0]), (235, 235, 235), 1, cv2.LINE_AA
        )
        cv2.line(
            panel, (0, idx), (panel.shape[1], idx), (235, 235, 235), 1, cv2.LINE_AA
        )
    center = panel.shape[0] // 2
    cv2.line(
        panel, (center, 0), (center, panel.shape[0]), (215, 215, 215), 1, cv2.LINE_AA
    )
    cv2.line(
        panel, (0, center), (panel.shape[1], center), (215, 215, 215), 1, cv2.LINE_AA
    )


def _normalized_to_canvas(points: np.ndarray, panel_size: int) -> np.ndarray:
    scaled = points.copy()
    scale = panel_size * 0.34
    center = panel_size / 2.0
    scaled[:, 0] = scaled[:, 0] * scale + center
    scaled[:, 1] = scaled[:, 1] * scale + center
    return scaled


def _draw_normalized_pose(
    panel: np.ndarray,
    points: np.ndarray,
    valid: np.ndarray,
    color: tuple[int, int, int],
    point_radius: int,
    limb_thickness: int,
) -> None:
    for start, end in BODY_LIMBS:
        if not (valid[start] and valid[end]):
            continue
        pt1 = tuple(np.round(points[start]).astype(int))
        pt2 = tuple(np.round(points[end]).astype(int))
        cv2.line(panel, pt1, pt2, color, limb_thickness, cv2.LINE_AA)
    for idx in BODY_KEYPOINT_IDS:
        if not valid[idx]:
            continue
        pt = tuple(np.round(points[idx]).astype(int))
        cv2.circle(panel, pt, point_radius, color, -1, cv2.LINE_AA)


def make_overlay_panel(
    norm_a: np.ndarray,
    valid_a: np.ndarray,
    norm_b: np.ndarray,
    valid_b: np.ndarray,
    panel_size: int,
    metrics: PoseMetrics,
) -> np.ndarray:
    panel = np.full((panel_size, panel_size, 3), 255, dtype=np.uint8)
    _draw_overlay_grid(panel)
    canvas_a = _normalized_to_canvas(norm_a, panel_size)
    canvas_b = _normalized_to_canvas(norm_b, panel_size)
    _draw_normalized_pose(
        panel,
        canvas_a,
        valid_a,
        POINT_COLOR_A,
        point_radius=max(panel_size // 85, 4),
        limb_thickness=max(panel_size // 130, 3),
    )
    _draw_normalized_pose(
        panel,
        canvas_b,
        valid_b,
        POINT_COLOR_B,
        point_radius=max(panel_size // 85, 4),
        limb_thickness=max(panel_size // 130, 3),
    )
    _draw_title(panel, "Normalized Overlay", "Blue: image A  Orange: image B")
    stats = [
        f"Pose score: {metrics.overall_score:.1f}/100",
        f"Angle sim: {metrics.angle_similarity * 100:.1f}",
        f"Position sim: {metrics.position_similarity * 100:.1f}",
        f"Symmetry sim: {metrics.symmetry_similarity * 100:.1f}",
        f"Matched joints: {metrics.matched_keypoints}/{len(BODY_KEYPOINT_IDS)}",
    ]
    base_y = panel_size - 114
    for idx, line in enumerate(stats):
        cv2.putText(
            panel,
            line,
            (18, base_y + idx * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            TEXT_COLOR,
            1,
            cv2.LINE_AA,
        )
    return panel


def compose_comparison_image(
    pose_a: PoseDetection,
    pose_b: PoseDetection,
    metrics: PoseMetrics,
    norm_a: np.ndarray,
    valid_a: np.ndarray,
    norm_b: np.ndarray,
    valid_b: np.ndarray,
    panel_size: int,
    score_thr: float,
) -> np.ndarray:
    panel_a = make_pose_panel(pose_a, panel_size, score_thr, "Image A")
    panel_overlay = make_overlay_panel(
        norm_a, valid_a, norm_b, valid_b, panel_size, metrics
    )
    panel_b = make_pose_panel(pose_b, panel_size, score_thr, "Image B")

    gap = 18
    header_height = 74
    footer_height = 56
    total_width = panel_size * 3 + gap * 4
    total_height = panel_size + header_height + footer_height
    canvas = np.full((total_height, total_width, 3), 245, dtype=np.uint8)

    title = "Pose Comparison"
    summary = (
        f"overall={metrics.overall_score:.1f}/100   "
        f"angle={metrics.angle_similarity * 100:.1f}   "
        f"position={metrics.position_similarity * 100:.1f}   "
        f"symmetry={metrics.symmetry_similarity * 100:.1f}   "
        f"visibility={metrics.visibility_ratio * 100:.1f}"
    )
    cv2.putText(
        canvas,
        title,
        (gap, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        TEXT_COLOR,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        summary,
        (gap, 58),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (80, 80, 80),
        1,
        cv2.LINE_AA,
    )

    y = header_height
    x_positions = [gap, gap * 2 + panel_size, gap * 3 + panel_size * 2]
    for x, panel in zip(x_positions, (panel_a, panel_overlay, panel_b)):
        canvas[y : y + panel_size, x : x + panel_size] = panel

    footer = (
        "The overlay uses normalized body joints, so scale and crop differences "
        "do not dominate the visual comparison."
    )
    cv2.putText(
        canvas,
        footer,
        (gap, total_height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (90, 90, 90),
        1,
        cv2.LINE_AA,
    )
    return canvas


def _joint_visible(scores: np.ndarray, idx: int, thr: float) -> bool:
    return idx < len(scores) and float(scores[idx]) >= thr


def _point_near_edge(
    point: np.ndarray,
    image_shape: tuple[int, int, int],
    *,
    margin_ratio: float = 0.08,
) -> bool:
    height, width = image_shape[:2]
    margin = max(12.0, min(height, width) * margin_ratio)
    x = float(point[0])
    y = float(point[1])
    return x <= margin or y <= margin or x >= width - margin or y >= height - margin


def _visible_hand_indices(
    scores: np.ndarray,
    offset: int,
    thr: float,
) -> list[int]:
    return [
        offset + idx
        for idx in range(21)
        if _joint_visible(scores, offset + idx, thr)
    ]


def _hand_is_central(
    pose: PoseDetection,
    *,
    offset: int,
    wrist_idx: int,
    thr: float,
) -> bool:
    visible_indices = _visible_hand_indices(pose.scores, offset, thr)
    points: list[np.ndarray] = []
    if _joint_visible(pose.scores, wrist_idx, thr):
        points.append(pose.keypoints[wrist_idx])
    points.extend(pose.keypoints[idx] for idx in visible_indices)
    if not points:
        return False
    center = np.mean(np.stack(points, axis=0), axis=0)
    return not _point_near_edge(center, pose.image.shape)


def _count_visible_fingers(scores: np.ndarray, offset: int, thr: float) -> tuple[int, int]:
    visible_fingers = 0
    partial_fingers = 0
    for chain in HAND_FINGER_CHAINS.values():
        count = sum(1 for idx in chain if _joint_visible(scores, offset + idx, thr))
        if count >= 3:
            visible_fingers += 1
        elif count >= 1:
            partial_fingers += 1
    return visible_fingers, partial_fingers


def inspect_pose_structure(
    pose: PoseDetection,
    *,
    score_thr: float = 0.3,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []

    for spec in MAJOR_LIMB_CHAINS.values():
        a, b, c = spec["joints"]
        label = spec["label"]
        a_visible = _joint_visible(pose.scores, a, score_thr)
        b_visible = _joint_visible(pose.scores, b, score_thr)
        c_visible = _joint_visible(pose.scores, c, score_thr)

        if a_visible and c_visible and not b_visible:
            if not _point_near_edge(pose.keypoints[a], pose.image.shape) and not _point_near_edge(
                pose.keypoints[c], pose.image.shape
            ):
                issues.append(
                    {
                        "severity": "fail",
                        "message": (
                            f"The {label} has a broken joint chain, which suggests a missing "
                            f"or duplicated limb segment."
                        ),
                    }
                )
                continue

        if a_visible and b_visible and c_visible:
            upper_length = float(np.linalg.norm(pose.keypoints[a] - pose.keypoints[b]))
            lower_length = float(np.linalg.norm(pose.keypoints[b] - pose.keypoints[c]))
            shorter = min(upper_length, lower_length)
            longer = max(upper_length, lower_length)
            if shorter > 1e-6 and longer / shorter >= 3.2:
                if not _point_near_edge(
                    np.mean([pose.keypoints[a], pose.keypoints[b], pose.keypoints[c]], axis=0),
                    pose.image.shape,
                ):
                    issues.append(
                        {
                            "severity": "uncertain",
                            "message": (
                                f"The {label} geometry looks abnormal, which can indicate an "
                                f"extra or missing limb artifact."
                            ),
                        }
                    )

    for hand_spec in HAND_SPECS.values():
        offset = hand_spec["offset"]
        wrist_idx = hand_spec["wrist_idx"]
        elbow_idx = hand_spec["elbow_idx"]
        label = hand_spec["label"]
        wrist_visible = _joint_visible(pose.scores, wrist_idx, score_thr)
        elbow_visible = _joint_visible(pose.scores, elbow_idx, score_thr)
        visible_indices = _visible_hand_indices(pose.scores, offset, score_thr)
        visible_joint_count = len(visible_indices)
        visible_fingers, partial_fingers = _count_visible_fingers(
            pose.scores,
            offset,
            score_thr,
        )
        hand_is_central = _hand_is_central(
            pose,
            offset=offset,
            wrist_idx=wrist_idx,
            thr=score_thr,
        )
        hand_likely_visible = hand_is_central and (
            (wrist_visible and elbow_visible) or visible_joint_count >= 8
        )
        if not hand_likely_visible:
            continue

        if visible_fingers <= 2 and visible_joint_count <= 10:
            issues.append(
                {
                    "severity": "fail",
                    "message": (
                        f"The {label} appears to be missing fingers or has a severely broken "
                        f"finger structure."
                    ),
                }
            )
            continue

        if visible_joint_count >= 14 and visible_fingers <= 3 and partial_fingers >= 2:
            issues.append(
                {
                    "severity": "uncertain",
                    "message": (
                        f"The {label} finger layout looks malformed or duplicated, which can "
                        f"correspond to extra-finger artifacts."
                    ),
                }
            )
            continue

        if visible_fingers <= 3:
            issues.append(
                {
                    "severity": "uncertain",
                    "message": (
                        f"The {label} shows incomplete finger coverage, which may indicate "
                        f"missing fingers."
                    ),
                }
            )

    overall_status = "pass"
    if any(issue["severity"] == "fail" for issue in issues):
        overall_status = "fail"
    elif issues:
        overall_status = "uncertain"

    if overall_status == "pass":
        summary = "No obvious limb or finger structural anomaly was detected."
    elif overall_status == "fail":
        summary = "Local DWPose found an obvious limb or finger structural defect."
    else:
        summary = "Local DWPose found a possible limb or finger structural anomaly."

    return {
        "status": overall_status,
        "summary": summary,
        "issues": issues,
        "obvious_failures": [
            issue["message"] for issue in issues if issue["severity"] == "fail"
        ],
        "suspect_dimensions": ["pose", "quality"] if issues else [],
    }


def inspect_pose_structure_source(
    image_source: str,
    *,
    models_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    score_thr: float = 0.3,
    download_timeout_seconds: int = 600,
) -> dict[str, Any]:
    model_resolution = resolve_models_dir(
        models_dir=models_dir,
        cache_dir=cache_dir,
        timeout_seconds=download_timeout_seconds,
    )
    _init_model_paths(str(model_resolution["models_dir"]))

    with tempfile.TemporaryDirectory(prefix="pose-structure-") as temp_root:
        temp_dir = Path(temp_root)
        image_path = _ensure_local_image(
            image_source,
            temp_dir,
            timeout_seconds=download_timeout_seconds,
        )
        pose = detect_primary_pose(image_path, load_image(str(image_path)))
        result = inspect_pose_structure(pose, score_thr=score_thr)

    result["models"] = {
        "models_dir": str(model_resolution["models_dir"]),
        "det_model_path": str(model_resolution["det_model_path"]),
        "pose_model_path": str(model_resolution["pose_model_path"]),
        "det_model_source": model_resolution["det_model_source"],
        "pose_model_source": model_resolution["pose_model_source"],
    }
    return result


def compare_pose_sources(
    image_a_source: str,
    image_b_source: str,
    *,
    models_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    score_thr: float = 0.3,
    panel_size: int = 440,
    download_timeout_seconds: int = 600,
) -> dict[str, Any]:
    model_resolution = resolve_models_dir(
        models_dir=models_dir,
        cache_dir=cache_dir,
        timeout_seconds=download_timeout_seconds,
    )
    _init_model_paths(str(model_resolution["models_dir"]))

    with tempfile.TemporaryDirectory(prefix="pose-compare-") as temp_root:
        temp_dir = Path(temp_root)
        image_a_path = _ensure_local_image(
            image_a_source,
            temp_dir,
            timeout_seconds=download_timeout_seconds,
        )
        image_b_path = _ensure_local_image(
            image_b_source,
            temp_dir,
            timeout_seconds=download_timeout_seconds,
        )

        pose_a = detect_primary_pose(image_a_path, load_image(str(image_a_path)))
        pose_b = detect_primary_pose(image_b_path, load_image(str(image_b_path)))
        metrics, norm_a, valid_a, norm_b, valid_b = score_pose_similarity(
            pose_a, pose_b, score_thr
        )

        result: dict[str, Any] = {
            "overall_score": round(metrics.overall_score, 2),
            "angle_similarity": round(metrics.angle_similarity, 4),
            "position_similarity": round(metrics.position_similarity, 4),
            "symmetry_similarity": round(metrics.symmetry_similarity, 4),
            "visibility_ratio": round(metrics.visibility_ratio, 4),
            "matched_keypoints": metrics.matched_keypoints,
            "total_keypoints": len(BODY_KEYPOINT_IDS),
            "mean_position_distance": round(metrics.mean_position_distance, 4),
            "mean_angle_difference": round(metrics.mean_angle_difference, 2),
            "models": {
                "models_dir": str(model_resolution["models_dir"]),
                "det_model_path": str(model_resolution["det_model_path"]),
                "pose_model_path": str(model_resolution["pose_model_path"]),
                "det_model_source": model_resolution["det_model_source"],
                "pose_model_source": model_resolution["pose_model_source"],
            },
        }

        if output_path:
            resolved_output_path = Path(output_path).expanduser().resolve()
            comparison = compose_comparison_image(
                pose_a,
                pose_b,
                metrics,
                norm_a,
                valid_a,
                norm_b,
                valid_b,
                panel_size,
                score_thr,
            )
            resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(resolved_output_path), comparison):
                raise OSError(f"Failed to write output image: {resolved_output_path}")
            result["output_image"] = str(resolved_output_path)

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def default_output_path(image_a: Path, image_b: Path) -> Path:
    output_dir = image_a.resolve().parent
    return output_dir / f"{image_a.stem}_vs_{image_b.stem}_pose_compare.png"


def main() -> None:
    args = parse_args()
    result = compare_pose_sources(
        args.image_a,
        args.image_b,
        models_dir=args.models_dir,
        cache_dir=args.cache_dir,
        output_path=args.output,
        score_thr=args.score_thr,
        panel_size=args.panel_size,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
