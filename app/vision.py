from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from app.detector import Detection, YoloDetector


@dataclass(frozen=True)
class VisionRunResult:
    results: list[dict]
    detections_for_output: list[Detection]


def run_yolo_detection(
    detector: YoloDetector,
    image: np.ndarray,
    targets: Iterable[str] | None = None,
    tolerance_ratio: float = 0.08,
    diagnostic_confidence: float | None = None,
) -> VisionRunResult:
    target_list = list(targets or [])

    if target_list:
        aim_results = [
            detector.aim_at(
                image,
                target=target,
                tolerance_ratio=tolerance_ratio,
                diagnostic_confidence=diagnostic_confidence,
            )
            for target in target_list
        ]
        detections_for_output = [
            detection
            for detection in (aim_result.detection for aim_result in aim_results)
            if detection is not None
        ]
        return VisionRunResult(
            results=[asdict(aim_result) for aim_result in aim_results],
            detections_for_output=detections_for_output,
        )

    detections = detector.detect(image)
    return VisionRunResult(
        results=[asdict(detection) for detection in detections],
        detections_for_output=detections,
    )
