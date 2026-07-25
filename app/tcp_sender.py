from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any

from app.face_recognition import FaceMatch


@dataclass(frozen=True)
class TcpTarget:
    host: str
    port: int
    timeout_seconds: float = 3.0


class TcpJsonLineClient:
    """Send one JSON object per line over a TCP connection."""

    def __init__(self, target: TcpTarget):
        self.target = target
        self._socket: socket.socket | None = None

    def send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        last_error: OSError | None = None

        try:
            self._connect().sendall(data)
            return
        except OSError as exc:
            last_error = exc
            self.close()

        raise ConnectionError(f"Could not send TCP payload to {self.target.host}:{self.target.port}") from last_error

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.close()
        finally:
            self._socket = None

    def _connect(self) -> socket.socket:
        if self._socket is None:
            self._socket = socket.create_connection(
                (self.target.host, self.target.port),
                timeout=self.target.timeout_seconds,
            )
        return self._socket


def build_face_tcp_payload(
    match: FaceMatch,
    sequence: int,
    camera_source: str,
    camera_index: int,
) -> dict[str, Any]:
    _ = (sequence, camera_source, camera_index)
    return build_face_status_tcp_payload(
        identity=match.identity,
        found=match.found,
        box=match.box,
    )


def build_face_status_tcp_payload(
    identity: str,
    found: bool,
    box: tuple[int, int, int, int] | None,
) -> dict[str, Any]:
    return build_vision_target_tcp_payload(identity=identity, found=found, box=box, status="find")


def build_vision_target_tcp_payload(
    identity: str,
    found: bool,
    box: tuple[int, int, int, int] | None,
    status: str = "find",
) -> dict[str, Any]:
    if status in {"home", "far"}:
        return {"status": status}
    return {
        "status": "find",
        "identity": identity,
        "found": found,
        "box": _box_payload(box) if found else None,
    }


def build_test_face_tcp_payload(identity: str = "zhangzhan") -> dict[str, Any]:
    return {
        "status": "find",
        "identity": identity,
        "found": True,
        "box": {
            "x1": 420,
            "y1": 160,
            "x2": 620,
            "y2": 420,
        },
    }


def _box_payload(box: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if box is None:
        return None
    x1, y1, x2, y2 = box
    return {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
    }
