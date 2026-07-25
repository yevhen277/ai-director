from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from typing import Any, Callable

from app.face_recognition import FaceMatch


@dataclass(frozen=True)
class TcpTarget:
    host: str
    port: int
    timeout_seconds: float = 3.0


class TcpJsonLineClient:
    """Send and optionally read JSON-line style messages over one TCP connection."""

    def __init__(self, target: TcpTarget, on_line: Callable[[str], None] | None = None):
        self.target = target
        self.on_line = on_line
        self._socket: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._closed = False
        self._lock = threading.Lock()

    def send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        last_error: OSError | None = None

        try:
            with self._lock:
                self._connect_locked().sendall(data)
            return
        except OSError as exc:
            last_error = exc
            self.close()

        raise ConnectionError(f"Could not send TCP payload to {self.target.host}:{self.target.port}") from last_error

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        self._closed = True
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _connect_locked(self) -> socket.socket:
        if self._socket is None:
            sock = socket.create_connection(
                (self.target.host, self.target.port),
                timeout=self.target.timeout_seconds,
            )
            sock.settimeout(None)
            self._socket = sock
            self._closed = False
            if self.on_line is not None:
                self._reader_thread = threading.Thread(
                    target=self._read_lines,
                    args=(sock,),
                    name=f"tcp-jsonline-reader-{self.target.host}-{self.target.port}",
                    daemon=True,
                )
                self._reader_thread.start()
        return self._socket

    def _read_lines(self, sock: socket.socket) -> None:
        buffer = b""
        try:
            while not self._closed:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._handle_line(line)
            if buffer.strip():
                self._handle_line(buffer)
        except OSError:
            pass

    def _handle_line(self, line: bytes) -> None:
        if self.on_line is None:
            return
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        self.on_line(text)


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
