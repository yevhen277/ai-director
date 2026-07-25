from __future__ import annotations

import threading
import time
import uuid
import logging
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import cv2

from app.camera import OpenCVCamera, OrbbecColorCamera
from app.config import settings
from app.detector import YoloDetector, draw_detections
from app.face_recognition import FaceRecognitionService, draw_face_matches, recognition_result_to_dict
from app.robot_joint_receiver import RobotJointStateHub
from app.tcp_sender import (
    TcpJsonLineClient,
    TcpTarget,
    build_vision_target_tcp_payload,
)
from app.vision import run_yolo_detection


RunStatus = Literal["starting", "running", "stopping", "stopped", "error"]
TcpTargetSource = Literal["object", "face"]
TcpTargetStatus = Literal["home", "far", "find"]
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


robot_joint_state_hub = RobotJointStateHub(default_unit=settings.robot_joint_tcp_default_unit)


class CameraRunConflictError(RuntimeError):
    pass


class CameraRunNotFoundError(KeyError):
    pass


class CameraRunValidationError(ValueError):
    pass


class CameraRunRecordingError(RuntimeError):
    pass


@dataclass
class SelectedTcpTarget:
    source_type: TcpTargetSource
    identity: str
    box: tuple[int, int, int, int]
    label: str | None = None
    latest_box: tuple[int, int, int, int] | None = None
    selected_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "identity": self.identity,
            "label": self.label,
            "box": list(self.box),
            "latest_box": list(self.latest_box) if self.latest_box is not None else None,
            "selected_at": self.selected_at,
        }


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
        self.recording_dir = output_root / self.run_name / "recordings"
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
        self._recording: dict | None = None
        self._box_payloads: deque[dict] = deque(maxlen=config.box_history_size)
        self._latest_box_payload: dict | None = None
        self._box_event_count = 0
        self._latest_face_result: dict | None = None
        self._latest_face_matches: list = []
        self._last_face_at: float | None = None
        self._latest_tcp_target_result: dict | None = None
        self._tcp_face_client: TcpJsonLineClient | None = None
        self._tcp_status: TcpTargetStatus = "home"
        self._selected_tcp_target: SelectedTcpTarget | None = None
        self._tcp_face_last_send: dict | None = None
        self._last_tcp_face_warning_at = 0.0
        self._tcp_face_warning_count = 0
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
        self._face_thread = threading.Thread(
            target=self._run_face_recognition,
            name=f"camera-face-{self.run_id}",
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
        if self.config.recognize_faces:
            self._face_thread.start()
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
        if self.config.recognize_faces:
            self._face_thread.join(timeout=timeout)
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
                "recording": self._recording_to_dict_locked(),
                "max_saved_images": self.config.max_saved_images,
                "frame_count": self.frame_count,
                "preview_frame_count": self.preview_frame_count,
                "preview_width": self.preview_width,
                "preview_height": self.preview_height,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "error": self.error,
                "latest_sample": self.latest_sample,
                "tcp_status": self._tcp_status,
                "tcp_target": self._selected_tcp_target.to_dict() if self._selected_tcp_target else None,
                "tcp_target_send": self._tcp_face_last_send,
            }

    def start_recording(self) -> dict:
        with self._lock:
            if self.status not in {"starting", "running"}:
                raise CameraRunRecordingError("Camera run is not active")
            if self._recording and self._recording.get("status") == "recording":
                raise CameraRunRecordingError("A recording is already active")

            recording_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            frames_dir = self.recording_dir / recording_id / "frames"
            video_path = self.recording_dir / f"{self.run_name}-{recording_id}.mp4"
            frames_dir.mkdir(parents=True, exist_ok=True)
            self._recording = {
                "id": recording_id,
                "status": "recording",
                "started_at": time.time(),
                "stopped_at": None,
                "frame_count": 0,
                "width": None,
                "height": None,
                "fps": self.config.preview_fps,
                "frames_dir": frames_dir,
                "video_path": video_path,
                "error": None,
            }
            return self._recording_to_dict_locked()

    def stop_recording(self) -> dict:
        with self._lock:
            if not self._recording or self._recording.get("status") != "recording":
                raise CameraRunRecordingError("No recording is active")
            recording = self._recording
            recording["status"] = "encoding"
            recording["stopped_at"] = time.time()

        try:
            self._encode_recording(recording)
        except Exception as exc:
            with self._lock:
                if self._recording is recording:
                    recording["status"] = "error"
                    recording["error"] = str(exc)
                    return self._recording_to_dict_locked()
            raise

        with self._lock:
            if self._recording is recording:
                recording["status"] = "ready"
                return self._recording_to_dict_locked()
            return self._recording_to_dict_locked()

    def recording_video_path(self, recording_id: str) -> Path | None:
        with self._lock:
            recording = self._recording
            if not recording or recording.get("id") != recording_id:
                return None
            video_path = recording.get("video_path")
            if recording.get("status") != "ready" or not video_path:
                return None
            return Path(video_path)

    def select_tcp_target(
        self,
        source_type: TcpTargetSource | None = None,
        identity: str | None = None,
        box: tuple[int, int, int, int] | None = None,
        label: str | None = None,
        status: TcpTargetStatus = "find",
    ) -> dict:
        if status not in {"home", "far", "find"}:
            raise CameraRunValidationError("status must be 'home', 'far', or 'find'")

        if status in {"home", "far"}:
            with self._lock:
                self._tcp_status = status
                self._selected_tcp_target = None
                self._latest_tcp_target_result = {
                    "enabled": self.config.tcp_face_enabled,
                    "status": status,
                    "selected": None,
                    "found": None,
                    "box": None,
                    "error": None,
                }
                if self.latest_sample is not None:
                    self.latest_sample["tcp_target"] = self._latest_tcp_target_result
            return {
                "run_id": self.run_id,
                "status": status,
                "tcp_target": None,
                "last_send": self._tcp_face_last_send,
            }

        identity = (identity or "").strip()
        label = label.strip() if label else None
        if not identity:
            raise CameraRunValidationError("identity cannot be empty")
        if source_type not in {"object", "face"}:
            raise CameraRunValidationError("source_type must be 'object' or 'face'")
        if box is None:
            raise CameraRunValidationError("box is required for find status")

        target = SelectedTcpTarget(
            source_type=source_type,
            identity=identity,
            label=label or (identity if source_type == "object" else None),
            box=box,
            latest_box=box,
            selected_at=time.time(),
        )
        with self._lock:
            self._tcp_status = "find"
            self._selected_tcp_target = target
            self._latest_tcp_target_result = {
                "enabled": self.config.tcp_face_enabled,
                "status": "find",
                "selected": target.to_dict(),
                "found": True,
                "box": box,
                "error": None,
            }
            if self.latest_sample is not None:
                self.latest_sample["tcp_target"] = self._latest_tcp_target_result
        return {
            "run_id": self.run_id,
            "status": "find",
            "tcp_target": target.to_dict(),
            "last_send": self._tcp_face_last_send,
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

    def _recording_to_dict_locked(self) -> dict | None:
        if not self._recording:
            return None
        recording = self._recording
        video_path = recording.get("video_path")
        return {
            "id": recording.get("id"),
            "status": recording.get("status"),
            "started_at": recording.get("started_at"),
            "stopped_at": recording.get("stopped_at"),
            "frame_count": recording.get("frame_count", 0),
            "width": recording.get("width"),
            "height": recording.get("height"),
            "fps": recording.get("fps"),
            "video_path": str(video_path) if video_path else None,
            "error": recording.get("error"),
        }

    def _record_frame_if_active_locked(self, frame) -> None:
        recording = self._recording
        if not recording or recording.get("status") != "recording":
            return
        frame_count = int(recording.get("frame_count") or 0) + 1
        frames_dir = Path(recording["frames_dir"])
        frame_path = frames_dir / f"frame-{frame_count:06d}.jpg"
        if not cv2.imwrite(str(frame_path), frame):
            recording["status"] = "error"
            recording["error"] = f"Could not write recording frame: {frame_path}"
            return
        height, width = frame.shape[:2]
        recording["frame_count"] = frame_count
        recording["width"] = width
        recording["height"] = height

    def _encode_recording(self, recording: dict) -> None:
        frame_count = int(recording.get("frame_count") or 0)
        if frame_count <= 0:
            raise CameraRunRecordingError("Recording has no frames")

        frames_dir = Path(recording["frames_dir"])
        video_path = Path(recording["video_path"])
        width = int(recording.get("width") or self.preview_width)
        height = int(recording.get("height") or self.preview_height)
        fps = max(1.0, float(recording.get("fps") or self.config.preview_fps))
        video_path.parent.mkdir(parents=True, exist_ok=True)

        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            raise CameraRunRecordingError(f"Could not open video writer: {video_path}")
        try:
            for index in range(1, frame_count + 1):
                frame_path = frames_dir / f"frame-{index:06d}.jpg"
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    continue
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)
        finally:
            writer.release()

        if not video_path.is_file() or video_path.stat().st_size <= 0:
            raise CameraRunRecordingError(f"Could not create video: {video_path}")

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
                        self._record_frame_if_active_locked(frame)
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
        tcp_target_result = None
        if self.config.recognize_faces:
            with self._lock:
                face_result = self._latest_face_result
                face_matches = list(self._latest_face_matches)
                tcp_target_result = self._latest_tcp_target_result

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
            "tcp_target": tcp_target_result,
        }

    def _run_face_recognition(self) -> None:
        next_face_at = self._started_monotonic
        while not self._stop_event.is_set():
            sleep_for = next_face_at - time.monotonic()
            if sleep_for > 0 and self._stop_event.wait(sleep_for):
                break

            frame_snapshot = None
            with self._frame_condition:
                self._frame_condition.wait_for(
                    lambda: self._stop_event.is_set() or self._latest_frame is not None or self.status == "error",
                    timeout=1.0,
                )
                if self._stop_event.is_set() or self.status == "error":
                    break
                if self._latest_frame is not None:
                    frame_snapshot = self._latest_frame.copy()

            if frame_snapshot is None:
                next_face_at = time.monotonic() + self.config.face_interval
                continue

            try:
                recognition_result = self.face_service.recognize_registered_identities(
                    image=frame_snapshot,
                    threshold=self.config.face_threshold,
                    include_fixed=self.config.include_fixed,
                    include_dynamic=self.config.include_dynamic,
                    auto_register_dynamic=self.config.auto_register_dynamic,
                    dynamic_prefix=self.config.dynamic_prefix,
                )
                face_result = recognition_result_to_dict(recognition_result)
                face_matches = list(recognition_result.matches)
            except Exception as exc:
                self._mark_done(status="error", error=str(exc))
                break

            with self._box_condition:
                if self.status == "error":
                    break
                self._latest_face_result = face_result
                self._latest_face_matches = face_matches
                self._last_face_at = time.monotonic()
                if self.latest_sample is not None:
                    self.latest_sample["face_recognition"] = face_result
                self._publish_box_payload_locked(sample=self.latest_sample)

            next_face_at += self.config.face_interval
            now = time.monotonic()
            if next_face_at < now:
                next_face_at = now + self.config.face_interval

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

    def _run_tcp_face_sender(self) -> None:
        interval = 1.0 / self.config.tcp_face_send_fps
        next_send_at = time.monotonic()

        try:
            while not self._stop_event.is_set():
                sleep_for = next_send_at - time.monotonic()
                if sleep_for > 0 and self._stop_event.wait(sleep_for):
                    break

                send_state = self._resolve_selected_tcp_target()
                if send_state is None:
                    next_send_at += interval
                    now = time.monotonic()
                    if next_send_at < now:
                        next_send_at = now + interval
                    continue

                status = send_state["status"]
                identity = send_state.get("identity") or ""
                found = bool(send_state.get("found"))
                box = send_state.get("box")
                payload = build_vision_target_tcp_payload(identity=identity, found=found, box=box, status=status)
                try:
                    self._tcp_face().send(payload)
                    with self._lock:
                        self._tcp_face_last_send = {
                            "sent": True,
                            "status": status,
                            "source_type": send_state.get("source_type"),
                            "identity": identity or None,
                            "found": send_state.get("found"),
                            "box": box,
                            "error": None,
                        }
                        self._latest_tcp_target_result = self._tcp_face_last_send.copy()
                        if self.latest_sample is not None:
                            self.latest_sample["tcp_target"] = self._latest_tcp_target_result
                    tcp_face_logger.info(
                        "sent target=%s:%s status=%s identity=%s found=%s box=%s",
                        self.config.tcp_face_host,
                        self.config.tcp_face_port,
                        status,
                        identity,
                        payload.get("found"),
                        payload.get("box"),
                    )
                except OSError as exc:
                    self._close_tcp_face_client()
                    with self._lock:
                        self._tcp_face_last_send = {
                            "sent": False,
                            "status": status,
                            "source_type": send_state.get("source_type"),
                            "identity": identity or None,
                            "found": send_state.get("found"),
                            "box": box,
                            "error": str(exc),
                        }
                        self._latest_tcp_target_result = self._tcp_face_last_send.copy()
                        if self.latest_sample is not None:
                            self.latest_sample["tcp_target"] = self._latest_tcp_target_result
                    self._tcp_face_warning_count += 1
                    if time.monotonic() - self._last_tcp_face_warning_at >= 1.0:
                        warning_count = self._tcp_face_warning_count
                        self._tcp_face_warning_count = 0
                        self._last_tcp_face_warning_at = time.monotonic()
                        tcp_face_logger.warning(
                            "failed target=%s:%s attempts=%s status=%s identity=%s found=%s box=%s error=%s",
                            self.config.tcp_face_host,
                            self.config.tcp_face_port,
                            warning_count,
                            status,
                            identity,
                            payload.get("found"),
                            payload.get("box"),
                            exc,
                        )

                next_send_at += interval
                now = time.monotonic()
                if next_send_at < now:
                    next_send_at = now + interval
        finally:
            self._close_tcp_face_client()

    def _resolve_selected_tcp_target(self) -> dict | None:
        with self._lock:
            status = self._tcp_status
            target = self._selected_tcp_target
            sample = self.latest_sample
            latest_face_result = self._latest_face_result
            if status in {"home", "far"}:
                return {"status": status}
            if target is None:
                return None
            target_box = target.latest_box or target.box

        face_recognition = (sample or {}).get("face_recognition") or latest_face_result or {}
        objects = _normalize_box_objects((sample or {}).get("results") or [])
        faces = _normalize_box_faces(face_recognition.get("matches") or [])

        if target.source_type == "face":
            matched = next((face for face in faces if face.get("identity") == target.identity), None)
        else:
            label = target.label or target.identity
            candidates = [item for item in objects if item.get("label") == label]
            matched = _nearest_box_item(candidates, target_box)

        matched_box = _tuple_box(matched.get("box")) if matched else None
        with self._lock:
            if self._selected_tcp_target is not target:
                return None
            if matched_box is not None:
                target.latest_box = matched_box
            result = {
                "status": "find",
                "source_type": target.source_type,
                "identity": target.identity,
                "found": matched_box is not None,
                "box": matched_box,
            }
            self._latest_tcp_target_result = result.copy()
            if self.latest_sample is not None:
                self.latest_sample["tcp_target"] = self._latest_tcp_target_result
            return result

    def _tcp_face(self) -> TcpJsonLineClient:
        if self._tcp_face_client is None:
            timeout_seconds = min(
                self.config.tcp_face_timeout_seconds,
                max(0.01, 0.5 / self.config.tcp_face_send_fps),
            )
            target = TcpTarget(
                host=self.config.tcp_face_host,
                port=self.config.tcp_face_port,
                timeout_seconds=timeout_seconds,
            )
            self._tcp_face_client = TcpJsonLineClient(
                target,
                on_line=lambda line: self._handle_tcp_joint_line(line, target),
            )
        return self._tcp_face_client

    def _handle_tcp_joint_line(self, line: str, target: TcpTarget) -> None:
        client = f"{target.host}:{target.port}"
        frame = robot_joint_state_hub.ingest_line(line, client=client, source="tcp_face_socket")
        if frame is None:
            return
        with self._lock:
            joint_payload = frame.to_payload()["data"]
            if self.latest_sample is not None:
                self.latest_sample["robot_joints"] = joint_payload

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

    def start_recording(self, run_id: str) -> dict:
        return self.get_run(run_id).start_recording()

    def stop_recording(self, run_id: str) -> dict:
        return self.get_run(run_id).stop_recording()

    def recording_video_path(self, run_id: str, recording_id: str) -> Path | None:
        return self.get_run(run_id).recording_video_path(recording_id)

    def preview_jpegs(self, run_id: str):
        return self.get_run(run_id).iter_preview_jpegs()

    def box_events(self, run_id: str):
        return self.get_run(run_id).iter_box_events()

    def select_tcp_target(
        self,
        run_id: str,
        source_type: TcpTargetSource | None = None,
        identity: str | None = None,
        box: tuple[int, int, int, int] | None = None,
        label: str | None = None,
        status: TcpTargetStatus = "find",
    ) -> dict:
        return self.get_run(run_id).select_tcp_target(
            source_type=source_type,
            identity=identity,
            box=box,
            label=label,
            status=status,
        )

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


def _tuple_box(box: Iterable | None) -> tuple[int, int, int, int] | None:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        return tuple(int(round(float(value))) for value in box)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _nearest_box_item(items: list[dict], previous_box: tuple[int, int, int, int] | None) -> dict | None:
    if not items:
        return None
    if previous_box is None:
        return items[0]
    prev_x, prev_y = _box_center(previous_box)

    def distance(item: dict) -> float:
        box = _tuple_box(item.get("box"))
        if box is None:
            return float("inf")
        x, y = _box_center(box)
        return (x - prev_x) ** 2 + (y - prev_y) ** 2

    return min(items, key=distance)


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
