from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Literal


JointUnit = Literal["deg", "rad"]

A1Z_LIMITS_RAD: tuple[tuple[float, float], ...] = (
    (-2.094, 2.094),
    (0.0, 3.142),
    (-3.142, 0.0),
    (-1.309, 1.309),
    (-1.484, 1.484),
    (-2.007, 2.007),
)


@dataclass(frozen=True)
class JointFrame:
    pos_rad: tuple[float, float, float, float, float, float]
    pos_deg: tuple[float, float, float, float, float, float]
    unit: JointUnit
    raw: str
    received_at: float
    client: str | None = None

    def to_payload(self) -> dict[str, Any]:
        age_ms = max(0.0, (time.time() - self.received_at) * 1000.0)
        return {
            "cmd": "status",
            "data": {
                "pos_deg": [round(value, 4) for value in self.pos_deg],
                "pos_rad": [round(value, 6) for value in self.pos_rad],
                "unit": self.unit,
                "source": "tcp",
                "client": self.client,
                "received_at": self.received_at,
                "age_ms": round(age_ms, 1),
            },
        }


def parse_joint_line(line: str, default_unit: JointUnit = "deg") -> JointFrame:
    raw = line.strip()
    if not raw:
        raise ValueError("empty joint payload")

    unit = default_unit
    values: Any
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON joint payload: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON joint payload must be an object")
        if "pos_rad" in payload:
            unit = "rad"
            values = payload["pos_rad"]
        elif "pos_deg" in payload:
            unit = "deg"
            values = payload["pos_deg"]
        elif "joints" in payload:
            values = payload["joints"]
            unit = _parse_unit(payload.get("unit", default_unit), default_unit)
        else:
            raise ValueError("JSON joint payload must contain pos_deg, pos_rad, or joints")
    else:
        values = [part.strip() for part in raw.split(",")]
        unit = default_unit

    parsed = _parse_six_numbers(values)
    if unit == "deg":
        pos_deg = tuple(parsed)
        pos_rad = tuple(math.radians(value) for value in parsed)
    else:
        pos_rad = tuple(parsed)
        pos_deg = tuple(math.degrees(value) for value in parsed)

    clamped_rad = _clamp_joints(pos_rad)
    clamped_deg = tuple(math.degrees(value) for value in clamped_rad)
    return JointFrame(
        pos_rad=clamped_rad,
        pos_deg=clamped_deg,
        unit=unit,
        raw=raw,
        received_at=time.time(),
    )


class RobotJointReceiver:
    def __init__(self, host: str, port: int, default_unit: JointUnit = "deg"):
        self.host = host
        self.port = port
        self.default_unit = default_unit
        self.enabled = False
        self.started_at: float | None = None
        self.last_frame: JointFrame | None = None
        self.last_error: str | None = None
        self.client_count = 0
        self._server: asyncio.AbstractServer | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._server is not None:
            return
        self.started_at = time.time()
        try:
            self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        except OSError as exc:
            self.last_error = f"Could not listen on {self.host}:{self.port}: {exc}"
            self.enabled = False
            return
        self.enabled = True
        self.last_error = None

    async def stop(self) -> None:
        server = self._server
        self._server = None
        self.enabled = False
        if server is not None:
            server.close()
            await server.wait_closed()
        for queue in list(self._subscribers):
            queue.put_nowait({"type": "robot_joints", "status": "stopped"})

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        if self.last_frame is not None:
            queue.put_nowait(self.last_frame.to_payload())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def status(self) -> dict[str, Any]:
        frame = self.last_frame
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "default_unit": self.default_unit,
            "started_at": self.started_at,
            "client_count": self.client_count,
            "last_error": self.last_error,
            "latest": frame.to_payload()["data"] if frame is not None else None,
        }

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        client = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) and len(peer) >= 2 else str(peer or "unknown")
        self.client_count += 1
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                line = data.decode("utf-8", errors="replace").strip()
                try:
                    frame = parse_joint_line(line, self.default_unit)
                    frame = JointFrame(
                        pos_rad=frame.pos_rad,
                        pos_deg=frame.pos_deg,
                        unit=frame.unit,
                        raw=frame.raw,
                        received_at=frame.received_at,
                        client=client,
                    )
                    async with self._lock:
                        self.last_frame = frame
                        self.last_error = None
                    self._publish(frame.to_payload())
                except ValueError as exc:
                    self.last_error = str(exc)
        finally:
            self.client_count = max(0, self.client_count - 1)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def _publish(self, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)


def _parse_unit(value: Any, default_unit: JointUnit) -> JointUnit:
    unit = str(value or default_unit).strip().lower()
    if unit in {"deg", "degree", "degrees"}:
        return "deg"
    if unit in {"rad", "radian", "radians"}:
        return "rad"
    raise ValueError("unit must be deg or rad")


def _parse_six_numbers(values: Any) -> tuple[float, float, float, float, float, float]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("joint payload must be a list of six numbers")
    if len(values) != 6:
        raise ValueError("joint payload must contain exactly six values")
    parsed: list[float] = []
    for index, value in enumerate(values):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"joint {index + 1} must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"joint {index + 1} must be finite")
        parsed.append(number)
    return tuple(parsed)  # type: ignore[return-value]


def _clamp_joints(values: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float]:
    return tuple(
        max(limit[0], min(limit[1], value))
        for value, limit in zip(values, A1Z_LIMITS_RAD, strict=True)
    )  # type: ignore[return-value]
