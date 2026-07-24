from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import cv2

from app.camera import OpenCVCamera, OrbbecColorCamera
from app.detector import YoloDetector, draw_detections
from app.face_recognition import FaceRecognitionService, draw_face_matches, recognition_result_to_dict
from app.vision import run_yolo_detection


RunStatus = Literal["starting", "running", "stopping", "stopped", "error"]


@dataclass(frozen=True)
class CameraRunConfig:
    camera_source: str = "orbbec"
    camera_index: int = 0
    name: str | None = None
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup: int = 5
    interval: float = 0.1
    targets: list[str] | None = None
    tolerance_ratio: float = 0.08
    diagnostic_confidence: float | None = None
    recognize_faces: bool = True
    include_fixed: bool = True
    include_dynamic: bool = True
    auto_register_dynamic: bool = True
    dynamic_prefix: str = "person"
    face_threshold: float | None = None
    max_saved_images: int = 100
    preview_fps: int = 10
    preview_jpeg_quality: int = 80


class CameraRunConflictError(RuntimeError):
    pass


class CameraRunNotFoundError(KeyError):
    pass


class CameraRunValidationError(ValueError):
    pass


class CameraRun:
    def __init__(
        self,
        config: CameraRunConfig,
        detector: YoloDetector,
        face_service: FaceRecognitionService,
        image_dir: Path = Path("images"),
        output_root: Path = Path("images") / "output",
        history_size: int = 1000,
    ):
        self.config = config
        self.detector = detector
        self.face_service = face_service
        self.run_id = str(uuid.uuid4())
        self.run_name = _clean_run_name(config.name or f"{config.camera_source}_{self.run_id[:8]}")
        self.input_dir = image_dir / self.run_name
        self.output_dir = output_root / self.run_name
        self.camera_key = (config.camera_source, config.camera_index)
        self.status: RunStatus = "starting"
        self.started_at = time.time()
        self.stopped_at: float | None = None
        self.error: str | None = None
        self.frame_count = 0
        self.preview_frame_count = 0
        self.preview_width = config.width
        self.preview_height = config.height
        self.latest_sample: dict | None = None
        self.frames: deque[dict] = deque(maxlen=history_size)
        self._saved_samples: deque[dict] = deque()
        self._lock = threading.Lock()
        self._frame_condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._latest_frame = None
        self._latest_preview_jpeg: bytes | None = None
        self._started_monotonic = time.monotonic()
        self._capture_thread = threading.Thread(
            target=self._run_capture,
            name=f"camera-capture-{self.run_id}",
            daemon=True,
        )
        self._analysis_thread = threading.Thread(
            target=self._run_analysis,
            name=f"camera-analysis-{self.run_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._capture_thread.start()
        self._analysis_thread.start()

    def stop(self, timeout: float = 5.0) -> dict:
        self._stop_event.set()
        with self._lock:
            if self.status in {"starting", "running"}:
                self.status = "stopping"
            self._frame_condition.notify_all()
        self._capture_thread.join(timeout=timeout)
        self._analysis_thread.join(timeout=timeout)
        return self.to_dict()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "run_id": self.run_id,
                "status": self.status,
                "run_name": self.run_name,
                "camera_source": self.config.camera_source,
                "camera_index": self.config.camera_index,
                "input_dir": str(self.input_dir),
                "output_dir": str(self.output_dir),
                "max_saved_images": self.config.max_saved_images,
                "frame_count": self.frame_count,
                "preview_frame_count": self.preview_frame_count,
                "preview_width": self.preview_width,
                "preview_height": self.preview_height,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "error": self.error,
                "latest_sample": self.latest_sample,
            }

    def recent_frames(self, limit: int) -> list[dict]:
        with self._lock:
            return list(self.frames)[-limit:]

    def latest_output_path(self) -> Path | None:
        with self._lock:
            if not self.latest_sample:
                return None
            output_path = self.latest_sample.get("output_path")
            return Path(output_path) if output_path else None

    def is_active(self) -> bool:
        with self._lock:
            return self.status in {"starting", "running", "stopping"}

    def iter_preview_jpegs(self):
        last_frame_count = 0
        while True:
            with self._frame_condition:
                self._frame_condition.wait_for(
                    lambda: (
                        self._stop_event.is_set()
                        or self.preview_frame_count != last_frame_count
                        or self.status == "error"
                    ),
                    timeout=1.0,
                )
                status = self.status
                frame_count = self.preview_frame_count
                jpeg = self._latest_preview_jpeg

            if jpeg is None:
                if status in {"stopped", "error"} or self._stop_event.is_set():
                    break
                continue
            if frame_count == last_frame_count:
                if status in {"stopped", "error"} or self._stop_event.is_set():
                    break
                continue

            last_frame_count = frame_count
            yield jpeg

    def _run_capture(self) -> None:
        try:
            self.input_dir.mkdir(parents=True, exist_ok=True)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with _open_camera(
                source=self.config.camera_source,
                camera_index=self.config.camera_index,
                width=self.config.width,
                height=self.config.height,
                fps=self.config.fps,
                warmup=self.config.warmup,
            ) as camera:
                with self._lock:
                    if self.status != "stopping":
                        self.status = "running"
                    self._frame_condition.notify_all()

                preview_interval = 1.0 / self.config.preview_fps
                next_frame_at = time.monotonic()
                while not self._stop_event.is_set():
                    sleep_for = next_frame_at - time.monotonic()
                    if sleep_for > 0 and self._stop_event.wait(sleep_for):
                        break

                    frame = camera.read()
                    success, encoded = cv2.imencode(
                        ".jpg",
                        frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), self.config.preview_jpeg_quality],
                    )
                    if not success:
                        raise RuntimeError("Could not encode preview frame")

                    height, width = frame.shape[:2]
                    with self._frame_condition:
                        self.preview_frame_count += 1
                        self.preview_width = width
                        self.preview_height = height
                        self._latest_frame = frame.copy()
                        self._latest_preview_jpeg = encoded.tobytes()
                        self._frame_condition.notify_all()

                    next_frame_at += preview_interval
                    now = time.monotonic()
                    if next_frame_at < now:
                        next_frame_at = now + preview_interval

            self._mark_done(status="stopped")
        except Exception as exc:
            self._mark_done(status="error", error=str(exc))

    def _run_analysis(self) -> None:
        frame_number = 1
        while not self._stop_event.is_set():
            due_time = self._started_monotonic + (frame_number - 1) * self.config.interval
            sleep_for = due_time - time.monotonic()
            if sleep_for > 0 and self._stop_event.wait(sleep_for):
                break

            frame_snapshot = None
            preview_frame_count = 0
            with self._frame_condition:
                self._frame_condition.wait_for(
                    lambda: self._stop_event.is_set() or self._latest_frame is not None or self.status == "error",
                    timeout=1.0,
                )
                if self._stop_event.is_set() or self.status == "error":
                    break
                if self._latest_frame is not None:
                    frame_snapshot = self._latest_frame.copy()
                    preview_frame_count = self.preview_frame_count

            if frame_snapshot is None:
                continue

            try:
                sample = self._run_sample(
                    frame=frame_snapshot,
                    frame_number=frame_number,
                    elapsed_seconds=round(time.monotonic() - self._started_monotonic, 3),
                    preview_frame_count=preview_frame_count,
                )
            except Exception as exc:
                self._mark_done(status="error", error=str(exc))
                break

            with self._lock:
                if self.status == "error":
                    break
                self.frame_count = frame_number
                self.latest_sample = sample
                self.frames.append(sample)
                self._saved_samples.append(sample)
            self._prune_saved_images()
            frame_number += 1

    def _run_sample(self, frame, frame_number: int, elapsed_seconds: float, preview_frame_count: int) -> dict:
        image_name = f"{self.run_name}-{frame_number:06d}.jpg"
        input_path = self.input_dir / image_name
        output_path = self.output_dir / image_name

        if not cv2.imwrite(str(input_path), frame):
            raise RuntimeError(f"Could not write input image: {input_path}")

        vision_result = run_yolo_detection(
            detector=self.detector,
            image=frame,
            targets=self.config.targets,
            tolerance_ratio=self.config.tolerance_ratio,
            diagnostic_confidence=self.config.diagnostic_confidence,
        )

        face_result = None
        face_matches: Iterable = []
        if self.config.recognize_faces:
            recognition_result = self.face_service.recognize_registered_identities(
                image=frame,
                threshold=self.config.face_threshold,
                include_fixed=self.config.include_fixed,
                include_dynamic=self.config.include_dynamic,
                auto_register_dynamic=self.config.auto_register_dynamic,
                dynamic_prefix=self.config.dynamic_prefix,
            )
            face_result = recognition_result_to_dict(recognition_result)
            face_matches = recognition_result.matches

        annotated = draw_detections(frame, vision_result.detections_for_output)
        if self.config.recognize_faces:
            annotated = draw_face_matches(annotated, face_matches)
        if not cv2.imwrite(str(output_path), annotated):
            raise RuntimeError(f"Could not write output image: {output_path}")

        return {
            "index": frame_number,
            "preview_frame_count": preview_frame_count,
            "elapsed_seconds": elapsed_seconds,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "results": vision_result.results,
            "face_recognition": face_result,
        }

    def _prune_saved_images(self) -> None:
        samples_to_delete = []
        with self._lock:
            while len(self._saved_samples) > self.config.max_saved_images:
                samples_to_delete.append(self._saved_samples.popleft())

        for sample in samples_to_delete:
            for key in ("input_path", "output_path"):
                path_value = sample.get(key)
                if not path_value:
                    continue
                try:
                    Path(path_value).unlink(missing_ok=True)
                except OSError:
                    pass

    def _mark_done(self, status: RunStatus, error: str | None = None) -> None:
        if status == "error":
            self._stop_event.set()
        with self._frame_condition:
            if status == "error":
                self.status = status
                self.error = error
            elif self.status != "error":
                self.status = "stopped" if self.status == "stopping" else status
            if status in {"stopped", "error"}:
                self.stopped_at = time.time()
            self._frame_condition.notify_all()


class CameraRunManager:
    def __init__(
        self,
        detector: YoloDetector,
        face_service: FaceRecognitionService,
        image_dir: Path = Path("images"),
        output_root: Path = Path("images") / "output",
    ):
        self.detector = detector
        self.face_service = face_service
        self.image_dir = image_dir
        self.output_root = output_root
        self._lock = threading.Lock()
        self._runs: dict[str, CameraRun] = {}

    def start_run(self, config: CameraRunConfig, replace_existing: bool = False) -> CameraRun:
        _validate_config(config)
        run = CameraRun(
            config=config,
            detector=self.detector,
            face_service=self.face_service,
            image_dir=self.image_dir,
            output_root=self.output_root,
        )
        replaced_run = None
        with self._lock:
            active = self._active_run_for_camera(run.camera_key)
            if active is not None:
                if not replace_existing:
                    raise CameraRunConflictError(
                        f"Camera {config.camera_source}:{config.camera_index} is already used by run {active.run_id}"
                    )
                replaced_run = active

        if replaced_run is not None:
            replaced_run.stop()

        with self._lock:
            active = self._active_run_for_camera(run.camera_key)
            if active is not None:
                raise CameraRunConflictError(
                    f"Camera {config.camera_source}:{config.camera_index} is still used by run {active.run_id}"
                )
            self._runs[run.run_id] = run
        run.start()
        return run

    def get_run(self, run_id: str) -> CameraRun:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise CameraRunNotFoundError(run_id)
        return run

    def stop_run(self, run_id: str) -> dict:
        run = self.get_run(run_id)
        return run.stop()

    def recent_frames(self, run_id: str, limit: int = 50) -> list[dict]:
        run = self.get_run(run_id)
        effective_limit = max(1, min(500, limit))
        return run.recent_frames(effective_limit)

    def latest_output_path(self, run_id: str) -> Path | None:
        return self.get_run(run_id).latest_output_path()

    def preview_jpegs(self, run_id: str):
        return self.get_run(run_id).iter_preview_jpegs()

    def _active_run_for_camera(self, camera_key: tuple[str, int]) -> CameraRun | None:
        for run in self._runs.values():
            if run.camera_key == camera_key and run.is_active():
                return run
        return None


def _open_camera(source: str, camera_index: int, width: int, height: int, fps: int, warmup: int):
    if source == "orbbec":
        return OrbbecColorCamera(
            device_index=camera_index,
            width=width,
            height=height,
            fps=fps,
            warmup=warmup,
        )
    if source == "opencv":
        return OpenCVCamera(camera_index=camera_index, width=width, height=height, warmup=warmup)
    raise RuntimeError(f"Unsupported camera source: {source}")


def _validate_config(config: CameraRunConfig) -> None:
    if config.camera_source not in {"orbbec", "opencv"}:
        raise CameraRunValidationError(f"Unsupported camera_source: {config.camera_source}")
    if config.camera_index < 0:
        raise CameraRunValidationError("camera_index must be greater than or equal to 0")
    if config.width <= 0 or config.height <= 0:
        raise CameraRunValidationError("width and height must be greater than 0")
    if config.fps <= 0:
        raise CameraRunValidationError("fps must be greater than 0")
    if config.warmup < 0:
        raise CameraRunValidationError("warmup must be greater than or equal to 0")
    if config.interval <= 0:
        raise CameraRunValidationError("interval must be greater than 0")
    if config.tolerance_ratio < 0:
        raise CameraRunValidationError("tolerance_ratio must be greater than or equal to 0")
    if not config.dynamic_prefix.strip():
        raise CameraRunValidationError("dynamic_prefix cannot be empty")
    if config.max_saved_images < 1:
        raise CameraRunValidationError("max_saved_images must be greater than or equal to 1")
    if config.preview_fps <= 0:
        raise CameraRunValidationError("preview_fps must be greater than 0")
    if config.preview_jpeg_quality < 1 or config.preview_jpeg_quality > 100:
        raise CameraRunValidationError("preview_jpeg_quality must be between 1 and 100")


def _clean_run_name(name: str) -> str:
    clean_name = Path(name).stem.strip()
    clean_name = clean_name[:-3] if len(clean_name) >= 3 and clean_name[-3] == "-" and clean_name[-2:].isdigit() else clean_name
    if not clean_name:
        raise CameraRunValidationError("run name cannot be empty")
    return clean_name
