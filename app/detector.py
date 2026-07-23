from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from ultralytics import YOLO

from app.labels import resolve_target_classes


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.box
        return max(0, x2 - x1) * max(0, y2 - y1)


@dataclass(frozen=True)
class AimResult:
    found: bool
    target: str
    accepted_labels: list[str]
    confidence_threshold: float
    image_size: int | tuple[int, int] | None
    frame_size: tuple[int, int]
    detection: Detection | None
    match_count: int
    detection_count: int
    labels_seen: list[str]
    miss_reason: str | None
    low_confidence_matches: list[Detection]
    offset: tuple[float, float] | None
    offset_ratio: tuple[float, float] | None
    command: str
    centered: bool


class YoloDetector:
    def __init__(
        self,
        model_path: str = "models/yolo26s.pt",
        confidence: float = 0.2,
        image_size: int | tuple[int, int] | None = None,
        end2end: bool | None = None,
    ):
        try:
            self.model = YOLO(model_path)
        except RuntimeError as exc:
            if "failed finding central directory" in str(exc):
                raise RuntimeError(
                    f"YOLO model file looks corrupted: {model_path}. "
                    "Delete it and download a complete .pt file again."
                ) from exc
            raise
        self.confidence = confidence
        self.image_size = image_size
        self.end2end = end2end

    @property
    def class_names(self) -> list[str]:
        names = self.model.names
        if isinstance(names, dict):
            return [names[index] for index in sorted(names)]
        return list(names)

    def detect(
        self,
        image: np.ndarray,
        confidence: float | None = None,
        image_size: int | tuple[int, int] | None = None,
    ) -> list[Detection]:
        predict_args = {
            "conf": self.confidence if confidence is None else confidence,
            "verbose": False,
        }
        effective_image_size = self.image_size if image_size is None else image_size
        if effective_image_size is not None:
            predict_args["imgsz"] = effective_image_size
        if self.end2end is not None:
            predict_args["end2end"] = self.end2end

        results = self.model.predict(image, **predict_args)
        detections: list[Detection] = []

        for result in results:
            names = result.names
            for box in result.boxes:
                class_id = int(box.cls[0])
                label = names[class_id]
                confidence = float(box.conf[0])
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                detections.append(Detection(label=label, confidence=confidence, box=(x1, y1, x2, y2)))

        return detections

    def aim_at(
        self,
        image: np.ndarray,
        target: str,
        tolerance_ratio: float = 0.08,
        diagnostic_confidence: float | None = None,
    ) -> AimResult:
        height, width = image.shape[:2]
        accepted_labels = resolve_target_classes(target)
        accepted_label_set = set(accepted_labels)
        detections = self.detect(image)
        matches = [d for d in detections if d.label in accepted_label_set]
        labels_seen = sorted({d.label for d in detections})
        low_confidence_matches = self._find_low_confidence_matches(
            image=image,
            accepted_labels=accepted_label_set,
            existing_matches=matches,
            diagnostic_confidence=diagnostic_confidence,
        )

        if not matches:
            miss_reason = "no_detections" if not detections else "no_matching_labels"
            if low_confidence_matches:
                miss_reason = "only_low_confidence_matches"
            return AimResult(
                found=False,
                target=target,
                accepted_labels=accepted_labels,
                confidence_threshold=self.confidence,
                image_size=self.image_size,
                frame_size=(width, height),
                detection=None,
                match_count=0,
                detection_count=len(detections),
                labels_seen=labels_seen,
                miss_reason=miss_reason,
                low_confidence_matches=low_confidence_matches,
                offset=None,
                offset_ratio=None,
                command="search",
                centered=False,
            )

        best = max(matches, key=lambda d: (d.confidence, d.area))
        center_x, center_y = best.center
        offset_x = center_x - width / 2
        offset_y = center_y - height / 2
        ratio_x = offset_x / width
        ratio_y = offset_y / height
        centered = abs(ratio_x) <= tolerance_ratio and abs(ratio_y) <= tolerance_ratio

        if centered:
            command = "hold"
        elif abs(ratio_x) >= abs(ratio_y):
            command = "pan_right" if ratio_x > 0 else "pan_left"
        else:
            command = "tilt_down" if ratio_y > 0 else "tilt_up"

        return AimResult(
            found=True,
            target=target,
            accepted_labels=accepted_labels,
            confidence_threshold=self.confidence,
            image_size=self.image_size,
            frame_size=(width, height),
            detection=best,
            match_count=len(matches),
            detection_count=len(detections),
            labels_seen=labels_seen,
            miss_reason=None,
            low_confidence_matches=low_confidence_matches,
            offset=(offset_x, offset_y),
            offset_ratio=(ratio_x, ratio_y),
            command=command,
            centered=centered,
        )

    def _find_low_confidence_matches(
        self,
        image: np.ndarray,
        accepted_labels: set[str],
        existing_matches: list[Detection],
        diagnostic_confidence: float | None,
    ) -> list[Detection]:
        if diagnostic_confidence is None or diagnostic_confidence >= self.confidence:
            return []
        diagnostic_detections = self.detect(image, confidence=diagnostic_confidence)
        existing_boxes = {d.box for d in existing_matches}
        return [
            d
            for d in diagnostic_detections
            if d.label in accepted_labels and d.box not in existing_boxes and d.confidence < self.confidence
        ]


def load_image(path: str | Path) -> np.ndarray:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Image file not found: {path}")

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def draw_detections(image: np.ndarray, detections: Iterable[Detection]) -> np.ndarray:
    output = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = detection.box
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 80), 2)
        text = f"{detection.label} {detection.confidence:.2f}"
        cv2.putText(output, text, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 80), 2)
    return output
