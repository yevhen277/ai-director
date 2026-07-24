from __future__ import annotations

import os
import time

import cv2
import numpy as np


class OpenCVCamera:
    def __init__(self, camera_index: int = 0, width: int = 1280, height: int = 720, warmup: int = 5):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.warmup = warmup
        self.capture = None

    def __enter__(self):
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.capture = cv2.VideoCapture(self.camera_index, backend)
        if not self.capture.isOpened():
            raise RuntimeError(f"Could not open OpenCV camera index {self.camera_index}")

        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.read(warmup=self.warmup)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def read(self, warmup: int = 1) -> np.ndarray:
        if self.capture is None:
            raise RuntimeError("OpenCV camera is not open")

        frame = None
        ok = False
        for _ in range(max(1, warmup)):
            ok, frame = self.capture.read()

        if not ok or frame is None:
            raise RuntimeError(f"Could not read OpenCV camera index {self.camera_index}")
        return frame


class OrbbecColorCamera:
    def __init__(
        self,
        device_index: int = 0,
        width: int | None = 1280,
        height: int | None = 720,
        fps: int = 30,
        warmup: int = 5,
        timeout_ms: int = 1000,
        open_retries: int = 3,
        open_retry_delay: float = 1.0,
    ):
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self.warmup = warmup
        self.timeout_ms = timeout_ms
        self.open_retries = open_retries
        self.open_retry_delay = open_retry_delay
        self.pipeline = None

    def __enter__(self):
        try:
            from pyorbbecsdk import Config, Context, OBError, OBSensorType, Pipeline
        except ImportError as exc:
            raise RuntimeError("pyorbbecsdk2 is not installed. Install it before using Orbbec cameras.") from exc

        self._ob_error = OBError
        attempts = max(1, self.open_retries)
        for attempt in range(attempts):
            try:
                self.context = Context()
                devices = self.context.query_devices()
                if devices.get_count() == 0:
                    raise RuntimeError("No Orbbec device found")
                if self.device_index < 0 or self.device_index >= devices.get_count():
                    raise RuntimeError(
                        f"Orbbec device index {self.device_index} is out of range; found {devices.get_count()} device(s)"
                    )

                device = devices.get_device_by_index(self.device_index)
                self.pipeline = Pipeline(device)
                config = Config()

                profiles = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
                profile = _choose_color_profile(profiles, width=self.width, height=self.height, fps=self.fps)
                config.enable_stream(profile)
                self.pipeline.start(config)
                self.read(warmup=self.warmup)
                return self
            except OBError as exc:
                self.__exit__(None, None, None)
                if attempt + 1 < attempts and _is_retryable_orbbec_error(exc):
                    time.sleep(max(0.0, self.open_retry_delay))
                    continue
                self._raise_orbbec_runtime_error(exc)
            except Exception:
                self.__exit__(None, None, None)
                raise

        raise RuntimeError("Could not open Orbbec camera")

    def __exit__(self, exc_type, exc, traceback):
        if self.pipeline is not None:
            try:
                self.pipeline.stop()
            except Exception:
                pass
            self.pipeline = None

    def read(self, warmup: int = 1) -> np.ndarray:
        if self.pipeline is None:
            raise RuntimeError("Orbbec camera is not open")

        try:
            frame = None
            for _ in range(max(1, warmup)):
                frames = self.pipeline.wait_for_frames(self.timeout_ms)
                if frames is None:
                    continue
                color_frame = frames.get_color_frame()
                if color_frame is not None:
                    frame = color_frame

            if frame is None:
                raise RuntimeError("Could not read Orbbec color frame")

            image = _orbbec_frame_to_bgr(frame)
            if image is None:
                raise RuntimeError(f"Could not convert Orbbec color frame format {frame.get_format()}")
            return image
        except self._ob_error as exc:
            self._raise_orbbec_runtime_error(exc)

    def _raise_orbbec_runtime_error(self, exc):
        raise _build_orbbec_runtime_error(exc, action=f"open Orbbec device index {self.device_index}") from exc


def capture_opencv_frame(camera_index: int = 0, width: int = 1280, height: int = 720, warmup: int = 5) -> np.ndarray:
    with OpenCVCamera(camera_index=camera_index, width=width, height=height, warmup=warmup) as camera:
        return camera.read()


def capture_orbbec_color_frame(
    device_index: int = 0,
    width: int | None = 1280,
    height: int | None = 720,
    fps: int = 30,
    warmup: int = 5,
    timeout_ms: int = 1000,
    open_retries: int = 3,
    open_retry_delay: float = 1.0,
) -> np.ndarray:
    with OrbbecColorCamera(
        device_index=device_index,
        width=width,
        height=height,
        fps=fps,
        warmup=warmup,
        timeout_ms=timeout_ms,
        open_retries=open_retries,
        open_retry_delay=open_retry_delay,
    ) as camera:
        return camera.read()


def list_orbbec_devices() -> list[dict]:
    try:
        from pyorbbecsdk import Context, OBError
    except ImportError as exc:
        raise RuntimeError("pyorbbecsdk2 is not installed. Install it before using Orbbec cameras.") from exc

    try:
        context = Context()
        devices = context.query_devices()
    except OBError as exc:
        raise _build_orbbec_runtime_error(exc, action="list Orbbec devices") from exc

    result = []
    for index in range(devices.get_count()):
        try:
            device = devices.get_device_by_index(index)
            info = device.get_device_info()
        except OBError as exc:
            raise _build_orbbec_runtime_error(exc, action=f"read Orbbec device index {index}") from exc
        result.append(
            {
                "index": index,
                "name": info.get_name(),
                "serial_number": info.get_serial_number(),
                "firmware_version": info.get_firmware_version(),
                "hardware_version": info.get_hardware_version(),
                "vid": f"0x{info.get_vid():04X}",
                "pid": f"0x{info.get_pid():04X}",
                "connection_type": info.get_connection_type(),
            }
        )
    return result


def _is_retryable_orbbec_error(exc) -> bool:
    message = str(exc)
    retryable_fragments = (
        "responsesize",
        "response header size",
        "propertyId: 2001",
        "statusCode: 8",
        "setXu",
        "0xc00d3704",
        "MFT",
    )
    return any(fragment in message for fragment in retryable_fragments)


def _build_orbbec_runtime_error(exc, action: str) -> RuntimeError:
    message = str(exc)
    if "0xc00d3704" in message or "MFT" in message:
        return RuntimeError(
            f"Orbbec SDK could not {action}: the color stream is busy or Windows Media Foundation could not start it. "
            "Close Orbbec Viewer and other camera apps, then try again."
        )
    if (
        "responsesize" in message
        or "response header size" in message
        or "propertyId: 2001" in message
        or "statusCode: 8" in message
        or "setXu" in message
    ):
        return RuntimeError(
            f"Orbbec SDK could see a device but could not {action}: the USB control response was invalid. "
            "Close Orbbec Viewer and other camera apps, unplug/replug the camera, use a direct USB 3 port, "
            "then run with --list-orbbec before starting the live sender again. "
            f"SDK detail: {exc}"
        )
    return RuntimeError(f"Orbbec SDK error while trying to {action}: {exc}")


def _choose_color_profile(profiles, width: int | None, height: int | None, fps: int):
    from pyorbbecsdk import OBFormat

    preferred_formats = [
        OBFormat.BGR,
        OBFormat.RGB,
        OBFormat.BGRA,
        OBFormat.RGBA,
        OBFormat.YUYV,
        OBFormat.UYVY,
        OBFormat.MJPG,
    ]

    if width and height:
        for preferred_format in preferred_formats:
            profile = _find_video_profile(profiles, width, height, fps, preferred_format)
            if profile is not None:
                return profile

        for preferred_format in preferred_formats:
            profile = _find_video_profile(profiles, width, height, None, preferred_format)
            if profile is not None:
                return profile

    return profiles.get_default_video_stream_profile()


def _find_video_profile(profiles, width: int, height: int, fps: int | None, color_format):
    for index in range(profiles.get_count()):
        profile = profiles.get_stream_profile_by_index(index).as_video_stream_profile()
        if profile.get_width() != width or profile.get_height() != height:
            continue
        if fps is not None and profile.get_fps() != fps:
            continue
        if profile.get_format() == color_format:
            return profile
    return None


def _orbbec_frame_to_bgr(frame):
    from pyorbbecsdk import FormatConvertFilter, OBConvertFormat, OBFormat

    width = frame.get_width()
    height = frame.get_height()
    data = np.asanyarray(frame.get_data())
    color_format = frame.get_format()

    if color_format == OBFormat.RGB:
        image = np.resize(data, (height, width, 3))
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if color_format == OBFormat.BGR:
        return np.resize(data, (height, width, 3))
    if color_format == OBFormat.RGBA:
        image = np.resize(data, (height, width, 4))
        return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
    if color_format == OBFormat.BGRA:
        image = np.resize(data, (height, width, 4))
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    if color_format == OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if color_format == OBFormat.YUYV:
        image = np.resize(data, (height, width, 2))
        return cv2.cvtColor(image, cv2.COLOR_YUV2BGR_YUYV)
    if color_format == OBFormat.UYVY:
        image = np.resize(data, (height, width, 2))
        return cv2.cvtColor(image, cv2.COLOR_YUV2BGR_UYVY)

    convert_formats = {
        OBFormat.I420: OBConvertFormat.I420_TO_RGB888,
        OBFormat.NV12: OBConvertFormat.NV12_TO_RGB888,
        OBFormat.NV21: OBConvertFormat.NV21_TO_RGB888,
    }
    convert_format = convert_formats.get(color_format)
    if convert_format is None:
        return None

    convert_filter = FormatConvertFilter()
    convert_filter.set_format_convert_format(convert_format)
    rgb_frame = convert_filter.process(frame)
    if rgb_frame is None:
        return None

    converted = np.asanyarray(rgb_frame.get_data())
    image = np.resize(converted, (rgb_frame.get_height(), rgb_frame.get_width(), 3))
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
