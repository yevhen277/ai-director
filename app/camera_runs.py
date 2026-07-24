from __future__ import annotations

import threading
import time
import uuid
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import cv2

from app.camera import OpenCVCamera, OrbbecColorCamera
from app.detector import YoloDetector, draw_detections
from app.face_recognition import FaceRecognitionService, draw_face_matches, recognition_result_to_dict
from app.tcp_sender import (
    TcpJsonLineClient,
    TcpTarget,
    build_face_status_tcp_payload,
)
from app.vision import run_yolo_detection


RunStatus = Literal["starting", "running", "stopping", "stopped", "error"]
TCP_FACE_LOG_PATH = Path("Log") / "tcp_face_auto.log"
tcp_face_logger = logging.getLogger("director.tcp_face")
if not tcp_face_logger.handlers:
    TCP_FACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(TCP_FACE_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    tcp_face_logger.addHandler(handler)
    tcp_face_logger.setLevel(logging.INFO)
    tcp_face_logger.propagate = False


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
    face_interval: float = 1.0
    box_history_size: int = 1
    tcp_face_enabled: bool = False
    tcp_face_host: str = "192.168.1.101"
    tcp_face_port: int = 9000
    tcp_face_identity: str = "zhangzhan"
    tcp_face_timeout_seconds: float = 0.2
    tcp_face_send_fps: int = 10
    tcp_face_track_ttl_seconds: float = 1.0


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
        self._box_condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._latest_frame = None
        self._latest_preview_jpeg: bytes | None = None
        self._box_payloads: deque[dict] = deque(maxlen=config.box_history_size)
        self._latest_box_payload: dict | None = None
        self._box_event_count = 0
        self._latest_face_result: dict | None = None
        self._latest_face_matches: list = []
        self._last_face_at: float | None = None
        self._tcp_face_client: TcpJsonLineClient | None = None
        self._tcp_face_box: tuple[int, int, int, int] | None = None
        self._tcp_face_template = None
        self._tcp_face_found = False
        self._tcp_face_last_seen_at: float | None = None
        self._tcp_face_last_send: dict | None = None
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
        self._tcp_face_thread = threading.Thread(
            target=self._run_tcp_face_sender,
            name=f"camera-tcp-face-{self.run_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._capture_thread.start()
        self._analysis_thread.start()
        if self.config.tcp_face_enabled:
            self._tcp_face_thread.start()

    def stop(self, timeout: float = 5.0) -> dict:
        self._stop_event.set()
        with self._lock:
            if self.status in {"starting", "running"}:
                self.status = "stopping"
            self._frame_condition.notify_all()
            self._box_condition.notify_all()
        self._capture_thread.join(timeout=timeout)
        self._analysis_thread.join(timeout=timeout)
        if self.config.tcp_face_enabled:
            self._tcp_face_thread.join(timeout=timeout)
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

    def iter_box_events(self):
        last_event_count = 0
        while True:
            with self._box_condition:
                self._box_condition.wait_for(
                    lambda: (
                        self._stop_event.is_set()
                        or self._box_event_count != last_event_count
                        or self.status in {"stopped", "error"}
                    ),
                    timeout=1.0,
                )
                status = self.status
                event_count = self._box_event_count
                payload = self._latest_box_payload

            if payload is not None and event_count != last_event_count:
                last_event_count = event_count
                yield payload
            if status in {"stopped", "error"} or self._stop_event.is_set():
                break

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
        try:
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

                now = time.monotonic()
                with self._lock:
                    run_face_recognition = (
                        self.config.recognize_faces
                        and (
                            self._last_face_at is None
                            or now - self._last_face_at >= self.config.face_interval
                        )
                    )

                try:
                    sample = self._run_sample(
                        frame=frame_snapshot,
                        frame_number=frame_number,
                        elapsed_seconds=round(time.monotonic() - self._started_monotonic, 3),
                        preview_frame_count=preview_frame_count,
                        run_face_recognition=run_face_recognition,
                    )
                except Exception as exc:
                    self._mark_done(status="error", error=str(exc))
                    break

                with self._box_condition:
                    if self.status == "error":
                        break
                    self.frame_count = frame_number
                    self.latest_sample = sample
                    self.frames.append(sample)
                    self._saved_samples.append(sample)
                    self._publish_box_payload_locked(sample=sample)
                self._prune_saved_images()
                frame_number += 1
        finally:
            pass

    def _run_sample(
        self,
        frame,
        frame_number: int,
        elapsed_seconds: float,
        preview_frame_count: int,
        run_face_recognition: bool,
    ) -> dict:
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
        recognition_result = None
        if self.config.recognize_faces and run_face_recognition:
            recognition_result = self.face_service.recognize_registered_identities(
                image=frame,
                threshold=self.config.face_threshold,
                include_fixed=self.config.include_fixed,
                include_dynamic=self.config.include_dynamic,
                auto_register_dynamic=self.config.auto_register_dynamic,
                dynamic_prefix=self.config.dynamic_prefix,
            )
            face_result = recognition_result_to_dict(recognition_result)
            face_matches = list(recognition_result.matches)
            with self._lock:
                self._latest_face_result = face_result
                self._latest_face_matches = list(face_matches)
                self._last_face_at = time.monotonic()
        elif self.config.recognize_faces:
            with self._lock:
                face_result = self._latest_face_result
                face_matches = list(self._latest_face_matches)
        tcp_face_result = self._update_tcp_face_tracking(
            recognition_result=recognition_result,
            frame=frame,
        )

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
            "tcp_face": tcp_face_result,
        }

    def _publish_box_payload_locked(self, sample: dict | None = None) -> None:
        self._latest_box_payload = self._build_box_payload(sample=sample or self.latest_sample, status=self.status)
        self._box_payloads.append(self._latest_box_payload)
        self._box_event_count += 1
        self._box_condition.notify_all()

    def _build_box_payload(self, sample: dict | None, status: str) -> dict:
        face_recognition = (sample or {}).get("face_recognition") or {}
        return {
            "type": "vision_boxes",
            "run_id": self.run_id,
            "status": status,
            "frame_count": self.frame_count,
            "preview_frame_count": self.preview_frame_count,
            "width": self.preview_width,
            "height": self.preview_height,
            "objects": _normalize_box_objects((sample or {}).get("results") or []),
            "faces": _normalize_box_faces(face_recognition.get("matches") or []),
            "error": self.error,
        }

    def _update_tcp_face_tracking(self, recognition_result, frame) -> dict | None:
        if not self.config.tcp_face_enabled:
            return None

        identity = self.config.tcp_face_identity.strip()
        if not identity:
            return {"enabled": True, "found": False, "error": "tcp_face_identity is empty"}

        match = None
        if recognition_result is not None:
            match = next((candidate for candidate in recognition_result.matches if candidate.identity == identity), None)

        now = time.monotonic()
        match_box = match.box if match is not None and match.found and match.box is not None else None
        match_template = _crop_gray(frame, match_box) if match_box is not None else None

        with self._lock:
            if match_box is not None:
                self._tcp_face_box = match_box
                self._tcp_face_template = match_template
                self._tcp_face_found = True
                self._tcp_face_last_seen_at = now

            current_box = self._tcp_face_box
            current_template = self._tcp_face_template

        tracked_box = self._track_tcp_face_box(frame, current_box, current_template)
        tracked_template = _crop_gray(frame, tracked_box) if tracked_box is not None else None

        with self._lock:
            if tracked_box is not None:
                self._tcp_face_box = tracked_box
                if tracked_template is not None:
                    self._tcp_face_template = tracked_template
                self._tcp_face_found = True
                self._tcp_face_last_seen_at = now

            if self._tcp_face_last_seen_at is not None and now - self._tcp_face_last_seen_at > self.config.tcp_face_track_ttl_seconds:
                self._tcp_face_found = False
                self._tcp_face_box = None
                self._tcp_face_template = None

            found = self._tcp_face_found and self._tcp_face_box is not None
            return {
                "enabled": True,
                "identity": identity,
                "found": found,
                "box": self._tcp_face_box if found else None,
                "error": None,
            }

    def _track_tcp_face_box(self, frame, current_box, template) -> tuple[int, int, int, int] | None:
        if current_box is None or template is None or template.size == 0:
            return None

        height, width = frame.shape[:2]
        x1, y1, x2, y2 = current_box
        box_width = max(1, x2 - x1)
        box_height = max(1, y2 - y1)
        search_margin_x = int(box_width * 1.5)
        search_margin_y = int(box_height * 1.5)
        search_box = (
            max(0, x1 - search_margin_x),
            max(0, y1 - search_margin_y),
            min(width, x2 + search_margin_x),
            min(height, y2 + search_margin_y),
        )
        search = _crop_gray(frame, search_box)
        if search is None or search.size == 0:
            return None
        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            return None

        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        if max_value < 0.45:
            return None

        search_x1, search_y1, _, _ = search_box
        new_x1 = search_x1 + max_location[0]
        new_y1 = search_y1 + max_location[1]
        new_x2 = min(width - 1, new_x1 + template.shape[1])
        new_y2 = min(height - 1, new_y1 + template.shape[0])
        return (new_x1, new_y1, new_x2, new_y2)

    def _run_tcp_face_sender(self) -> None:
        identity = self.config.tcp_face_identity.strip()
        interval = 1.0 / self.config.tcp_face_send_fps
        next_send_at = time.monotonic()

        try:
            while not self._stop_event.is_set():
                sleep_for = next_send_at - time.monotonic()
                if sleep_for > 0 and self._stop_event.wait(sleep_for):
                    break

                with self._lock:
                    now = time.monotonic()
                    if self._tcp_face_last_seen_at is not None and now - self._tcp_face_last_seen_at > self.config.tcp_face_track_ttl_seconds:
                        self._tcp_face_found = False
                        self._tcp_face_box = None
                        self._tcp_face_template = None
                    found = self._tcp_face_found and self._tcp_face_box is not None
                    box = self._tcp_face_box if found else None

                payload = build_face_status_tcp_payload(identity=identity, found=found, box=box)
                try:
                    self._tcp_face().send(payload)
                    with self._lock:
                        self._tcp_face_last_send = {"sent": True, "identity": identity, "found": found, "error": None}
                    tcp_face_logger.info(
                        "sent target=%s:%s identity=%s found=%s box=%s",
                        self.config.tcp_face_host,
                        self.config.tcp_face_port,
                        identity,
                        payload["found"],
                        payload["box"],
                    )
                except OSError as exc:
                    self._close_tcp_face_client()
                    with self._lock:
                        self._tcp_face_last_send = {"sent": False, "identity": identity, "found": found, "error": str(exc)}
                    tcp_face_logger.warning(
                        "failed target=%s:%s identity=%s found=%s box=%s error=%s",
                        self.config.tcp_face_host,
                        self.config.tcp_face_port,
                        identity,
                        payload["found"],
                        payload["box"],
                        exc,
                    )

                next_send_at += interval
                now = time.monotonic()
                if next_send_at < now:
                    next_send_at = now + interval
        finally:
            self._close_tcp_face_client()

    def _tcp_face(self) -> TcpJsonLineClient:
        if self._tcp_face_client is None:
            self._tcp_face_client = TcpJsonLineClient(
                TcpTarget(
                    host=self.config.tcp_face_host,
                    port=self.config.tcp_face_port,
                    timeout_seconds=self.config.tcp_face_timeout_seconds,
                )
            )
        return self._tcp_face_client

    def _close_tcp_face_client(self) -> None:
        if self._tcp_face_client is None:
            return
        self._tcp_face_client.close()
        self._tcp_face_client = None

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
            self._publish_box_payload_locked(sample=self.latest_sample)
            self._frame_condition.notify_all()
            self._box_condition.notify_all()


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

    def box_events(self, run_id: str):
        return self.get_run(run_id).iter_box_events()

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
    if config.tcp_face_enabled:
        if not config.tcp_face_host.strip():
            raise CameraRunValidationError("tcp_face_host cannot be empty")
        if config.tcp_face_port <= 0 or config.tcp_face_port > 65535:
            raise CameraRunValidationError("tcp_face_port must be between 1 and 65535")
        if not config.tcp_face_identity.strip():
            raise CameraRunValidationError("tcp_face_identity cannot be empty")
        if config.tcp_face_timeout_seconds <= 0:
            raise CameraRunValidationError("tcp_face_timeout_seconds must be greater than 0")
        if config.tcp_face_send_fps <= 0:
            raise CameraRunValidationError("tcp_face_send_fps must be greater than 0")
        if config.tcp_face_track_ttl_seconds <= 0:
            raise CameraRunValidationError("tcp_face_track_ttl_seconds must be greater than 0")
    if config.max_saved_images < 1:
        raise CameraRunValidationError("max_saved_images must be greater than or equal to 1")
    if config.preview_fps <= 0:
        raise CameraRunValidationError("preview_fps must be greater than 0")
    if config.preview_jpeg_quality < 1 or config.preview_jpeg_quality > 100:
        raise CameraRunValidationError("preview_jpeg_quality must be between 1 and 100")
    if config.face_interval <= 0:
        raise CameraRunValidationError("face_interval must be greater than 0")
    if config.box_history_size < 1:
        raise CameraRunValidationError("box_history_size must be greater than or equal to 1")


def _normalize_box_objects(results: Iterable[dict]) -> list[dict]:
    objects = []
    for item in results:
        detection = item.get("detection") if isinstance(item, dict) and item.get("detection") else item
        if not isinstance(detection, dict):
            continue
        label = detection.get("label") or detection.get("object_name")
        box = detection.get("box")
        if not label or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        objects.append(
            {
                "label": label,
                "confidence": detection.get("confidence"),
                "box": [int(round(float(value))) for value in box],
            }
        )
    return objects


def _normalize_box_faces(matches: Iterable[dict]) -> list[dict]:
    faces = []
    for match in matches:
        if not isinstance(match, dict) or match.get("found") is False:
            continue
        box = match.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        faces.append(
            {
                "identity": match.get("identity") or "unknown",
                "similarity": match.get("similarity"),
                "library": match.get("library") or match.get("source_library") or match.get("source") or "unknown",
                "box": [int(round(float(value))) for value in box],
            }
        )
    return faces


def _box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _point_in_box(point: tuple[float, float], box: tuple[int, int, int, int]) -> bool:
    x, y = point
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def _box_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    left_x1, left_y1, left_x2, left_y2 = left
    right_x1, right_y1, right_x2, right_y2 = right
    inter_x1 = max(left_x1, right_x1)
    inter_y1 = max(left_y1, right_y1)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
    if inter_area == 0:
        return 0.0
    left_area = max(0, left_x2 - left_x1) * max(0, left_y2 - left_y1)
    right_area = max(0, right_x2 - right_x1) * max(0, right_y2 - right_y1)
    union_area = left_area + right_area - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def _center_distance_ratio(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    left_center_x, left_center_y = _box_center(left)
    right_center_x, right_center_y = _box_center(right)
    left_x1, left_y1, left_x2, left_y2 = left
    scale = max(1.0, ((left_x2 - left_x1) ** 2 + (left_y2 - left_y1) ** 2) ** 0.5)
    distance = ((left_center_x - right_center_x) ** 2 + (left_center_y - right_center_y) ** 2) ** 0.5
    return distance / scale


def _crop_gray(frame, box: tuple[int, int, int, int]):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width, x2))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def _clean_run_name(name: str) -> str:
    clean_name = Path(name).stem.strip()
    clean_name = clean_name[:-3] if len(clean_name) >= 3 and clean_name[-3] == "-" and clean_name[-2:].isdigit() else clean_name
    if not clean_name:
        raise CameraRunValidationError("run name cannot be empty")
    return clean_name
