from __future__ import annotations

import tempfile
import sys
import types
import unittest
from pathlib import Path
from time import time

import numpy as np

ultralytics_stub = types.ModuleType("ultralytics")
ultralytics_stub.YOLO = object
sys.modules.setdefault("ultralytics", ultralytics_stub)

from app.camera_runs import CameraRun, CameraRunConfig, CameraRunFaceRegistrationError, CameraRunValidationError
from app.face_recognition import FaceCandidate, FaceRecognitionService


class StubDetector:
    pass


class StubFaceService(FaceRecognitionService):
    def __init__(self, candidates: list[FaceCandidate], registry_path: Path):
        super().__init__(registry_path=registry_path)
        self.candidates = candidates

    def detect_faces(self, image: np.ndarray) -> list[FaceCandidate]:
        for candidate in self.candidates:
            self._candidates[candidate.face_id] = (time(), candidate)
        return self.candidates


def candidate(face_id: str, confidence: float) -> FaceCandidate:
    return FaceCandidate(
        face_id=face_id,
        box=(1, 2, 3, 4),
        confidence=confidence,
        embedding=np.ones(4, dtype=np.float32),
    )


class CameraRunFaceRegistrationTest(unittest.TestCase):
    def make_run(self, face_service: FaceRecognitionService) -> CameraRun:
        return CameraRun(config=CameraRunConfig(), detector=StubDetector(), face_service=face_service)  # type: ignore[arg-type]

    def test_registers_highest_confidence_face(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "face_registry.json"
            face_service = StubFaceService(
                candidates=[candidate("low", 0.3), candidate("high", 0.9)],
                registry_path=registry_path,
            )
            run = self.make_run(face_service)
            run._latest_frame = np.zeros((10, 10, 3), dtype=np.uint8)
            run.latest_sample = {"input_path": "images/input/current.jpg"}

            result = run.register_best_face("alice", threshold=0.5)
            self.assertEqual(result["registered"]["identity"], "alice")
            self.assertEqual(result["registered"]["source_face_id"], "high")
            self.assertEqual(result["registered"]["source_image"], "images/input/current.jpg")
            self.assertEqual(result["candidate"]["face_id"], "high")
            self.assertEqual(result["candidate"]["confidence"], 0.9)
            self.assertTrue(registry_path.is_file())

    def test_rejects_empty_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            face_service = StubFaceService([], Path(temp_dir) / "face_registry.json")
            run = self.make_run(face_service)

            with self.assertRaisesRegex(CameraRunValidationError, "identity"):
                run.register_best_face("  ")

    def test_rejects_missing_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            face_service = StubFaceService([], Path(temp_dir) / "face_registry.json")
            run = self.make_run(face_service)

            with self.assertRaisesRegex(CameraRunFaceRegistrationError, "No camera frame"):
                run.register_best_face("alice")

    def test_rejects_frame_without_faces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            face_service = StubFaceService([], Path(temp_dir) / "face_registry.json")
            run = self.make_run(face_service)
            run._latest_frame = np.zeros((10, 10, 3), dtype=np.uint8)

            with self.assertRaisesRegex(CameraRunFaceRegistrationError, "No face"):
                run.register_best_face("alice")


if __name__ == "__main__":
    unittest.main()
