from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple


JointUnit = Literal["deg", "rad"]

A1Z_LIMITS_RAD: tuple[tuple[float, float], ...] = (
    (-2.094, 2.094),
    (0.0, 3.142),
    (-3.142, 0.0),
    (-1.309, 1.309),
    (-1.484, 1.484),
    (-2.007, 2.007),
)

ROBOT_JOINT_LOG_PATH = Path("Log") / "robot_joints_tcp.log"
robot_joint_logger = logging.getLogger("director.robot_joints_tcp")
if not robot_joint_logger.handlers:
    ROBOT_JOINT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(ROBOT_JOINT_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    robot_joint_logger.addHandler(handler)
    robot_joint_logger.setLevel(logging.INFO)
    robot_joint_logger.propagate = False


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


class _Subscriber(NamedTuple):
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


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


class RobotJointStateHub:
    """Parse and broadcast joint feedback read from the existing robot TCP socket."""

    def __init__(self, default_unit: JointUnit = "deg"):
        self.default_unit = default_unit
        self.last_frame: JointFrame | None = None
        self.last_error: str | None = None
        self.last_source: str | None = None
        self._subscribers: set[_Subscriber] = set()

    def ingest_line(self, line: str, client: str | None = None, source: str = "tcp") -> JointFrame | None:
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
        except ValueError as exc:
            self.last_error = str(exc)
            self.last_source = source
            robot_joint_logger.warning("invalid client=%s source=%s error=%s raw=%r", client, source, exc, line)
            return None

        self.last_frame = frame
        self.last_error = None
        self.last_source = source
        robot_joint_logger.info(
            "received client=%s source=%s unit=%s pos_deg=%s pos_rad=%s raw=%r",
            client,
            source,
            frame.unit,
            [round(value, 4) for value in frame.pos_deg],
            [round(value, 6) for value in frame.pos_rad],
            frame.raw,
        )
        self._publish(frame.to_payload())
        return frame

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        subscriber = _Subscriber(loop=loop, queue=queue)
        self._subscribers.add(subscriber)
        if self.last_frame is not None:
            queue.put_nowait(self.last_frame.to_payload())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers = {subscriber for subscriber in self._subscribers if subscriber.queue is not queue}

    def status(self) -> dict[str, Any]:
        frame = self.last_frame
        return {
            "enabled": True,
            "transport": "existing_tcp_socket",
            "default_unit": self.default_unit,
            "last_source": self.last_source,
            "last_error": self.last_error,
            "latest": frame.to_payload()["data"] if frame is not None else None,
        }

    def _publish(self, payload: dict[str, Any]) -> None:
        for subscriber in list(self._subscribers):
            subscriber.loop.call_soon_threadsafe(_offer_latest, subscriber.queue, payload)


def _offer_latest(queue: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
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
