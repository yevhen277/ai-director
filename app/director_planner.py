from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import settings


JOINT_LIMITS = [
    (-2.094, 2.094),
    (0.0, 3.142),
    (-3.142, 0.0),
    (-1.309, 1.309),
    (-1.484, 1.484),
    (-2.007, 2.007),
]

SAFE_POSES = {
    "home": [0.007, 0.235, -0.898, 1.187, -0.006, 1.574],
    "close": [0.003, 0.675, -0.717, 0.677, -0.003, 1.573],
    "far": [0.030, 0.034, -0.899, 1.309, -0.023, 1.599],
    "top": [0.002, 1.320, -1.575, 1.309, -0.002, 1.506],
    "low": [-0.312, 1.020, 0.000, -0.818, 0.453, 1.577],
    "lowPre0": [-0.007, 0.506, -0.736, 0.824, 0.007, 1.566],
    "lowPre": [-0.062, 0.669, -0.478, 0.334, 0.079, 1.525],
    "lowPre2": [-0.121, 0.834, -0.239, -0.218, 0.178, 1.501],
    "orb0": [0.000, 0.191, -0.758, 1.061, -0.000, 1.571],
    "orbL1": [-0.230, 0.167, -0.751, 1.078, 0.209, 1.372],
    "orbL2": [-0.817, 0.000, -0.768, 1.309, 0.676, 1.036],
    "orbR1": [0.230, 0.167, -0.751, 1.078, -0.210, 1.770],
    "orbR2": [0.817, 0.000, -0.767, 1.309, -0.677, 2.007],
    "swpA": [0.357, 0.211, -0.983, 1.309, -0.285, 1.737],
    "swpB": [-0.358, 0.210, -0.982, 1.309, 0.286, 1.405],
}


class DirectorPlannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlannerInput:
    user_prompt: str
    vision_context: dict[str, Any] | None = None
    max_duration_seconds: float = 28.0


def generate_director_plan(planner_input: PlannerInput) -> dict[str, Any]:
    if not settings.llm_api_key:
        raise DirectorPlannerError("LLM_API_KEY is not configured")
    if not settings.llm_model:
        raise DirectorPlannerError("LLM_MODEL is not configured")

    raw_plan = _call_chat_completions(planner_input)
    return _validate_plan(raw_plan, max_duration_seconds=planner_input.max_duration_seconds)


def _call_chat_completions(planner_input: PlannerInput) -> dict[str, Any]:
    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": _system_prompt(planner_input.max_duration_seconds)},
            {"role": "user", "content": _user_prompt(planner_input)},
        ],
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.llm_timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DirectorPlannerError(f"LLM request failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise DirectorPlannerError(f"LLM request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DirectorPlannerError("LLM request timed out") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DirectorPlannerError("LLM response did not contain a message") from exc
    return _parse_json_object(content)


def _system_prompt(max_duration_seconds: float) -> str:
    return f"""
You are DirectorX, a robotic cinematography planner for a GALAXEA A1Z 6-axis arm carrying a camera on a Unitree Go2.
Return JSON only. No markdown.

Business goal:
- Convert the user's desired visual effect and the current camera detection context into an executable shot plan.
- The frontend will convert your keyframes to A1Z move commands, so every keyframe must be safe and numeric.

Output schema:
{{
  "title": "short plan title",
  "summary": "1 sentence, include subject and visual intent",
  "shots": [
    {{
      "name": "shot name",
      "tech": "ESTABLISH | DOLLY IN | DOLLY OUT | ARC ORBIT | TOP SHOT | LOW ANGLE | TRUCK SWEEP | HOLD | RECOVER",
      "desc": "what this shot accomplishes",
      "keyframes": [
        [[j1,j2,j3,j4,j5,j6], time_seconds]
      ],
      "t0": 0.0,
      "t1": 3.0
    }}
  ]
}}

Rules:
- Use 2 to 5 shots, total duration <= {max_duration_seconds:.1f} seconds.
- First keyframe of the first shot should usually be "home".
- Adjacent shots must connect smoothly: first keyframe of a shot should equal the previous shot's last pose at the same time.
- Each joint array has exactly 6 radians.
- Joint limits are: {JOINT_LIMITS}
- Prefer composing from these safe poses and small wrist yaw/roll adjustments: {json.dumps(SAFE_POSES)}
- If vision context says no person/face/object is visible, create a cautious search or establish plan and mention the uncertainty.
- If a known face identity is present, make that person the subject.
- Do not invent hardware commands, only return the ShotPlan JSON.
""".strip()


def _user_prompt(planner_input: PlannerInput) -> str:
    return json.dumps(
        {
            "user_prompt": planner_input.user_prompt,
            "vision_context": planner_input.vision_context or {},
        },
        ensure_ascii=False,
        indent=2,
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise DirectorPlannerError("LLM response was not JSON")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise DirectorPlannerError("LLM response JSON must be an object")
    return parsed


def _validate_plan(plan: dict[str, Any], max_duration_seconds: float) -> dict[str, Any]:
    shots = plan.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 8:
        raise DirectorPlannerError("Plan must contain 1 to 8 shots")

    validated_shots: list[dict[str, Any]] = []
    last_time = 0.0
    for shot_index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise DirectorPlannerError("Each shot must be an object")
        keyframes = shot.get("keyframes")
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            raise DirectorPlannerError("Each shot must contain at least 2 keyframes")

        validated_keyframes = []
        for frame in keyframes:
            if not isinstance(frame, list | tuple) or len(frame) != 2:
                raise DirectorPlannerError("Each keyframe must be [[q1..q6], t]")
            q, t = frame
            if not isinstance(q, list | tuple) or len(q) != 6:
                raise DirectorPlannerError("Each keyframe pose must contain exactly 6 joints")
            q_validated = [_clamp_joint(float(value), i) for i, value in enumerate(q)]
            t_value = float(t)
            if not math.isfinite(t_value):
                raise DirectorPlannerError("Keyframe time must be finite")
            if validated_keyframes and t_value < validated_keyframes[-1][1]:
                raise DirectorPlannerError("Keyframe times must be non-decreasing inside a shot")
            validated_keyframes.append([q_validated, round(t_value, 3)])

        if shot_index == 0 and validated_keyframes[0][1] != 0:
            validated_keyframes[0][1] = 0.0
        if validated_keyframes[0][1] < last_time - 0.001:
            raise DirectorPlannerError("Shot timeline moved backwards")

        t0 = validated_keyframes[0][1]
        t1 = validated_keyframes[-1][1]
        if t1 <= t0:
            raise DirectorPlannerError("Shot duration must be positive")
        last_time = t1
        validated_shots.append(
            {
                "name": str(shot.get("name") or f"Shot {shot_index + 1}")[:80],
                "tech": str(shot.get("tech") or "HOLD")[:40],
                "desc": str(shot.get("desc") or "")[:240],
                "keyframes": validated_keyframes,
                "t0": round(t0, 3),
                "t1": round(t1, 3),
            }
        )

    total = validated_shots[-1]["t1"]
    if total > max_duration_seconds + 0.001:
        raise DirectorPlannerError(f"Plan duration {total:.1f}s exceeds {max_duration_seconds:.1f}s")

    return {
        "title": str(plan.get("title") or "DirectorX Plan")[:100],
        "summary": str(plan.get("summary") or f"{len(validated_shots)} shots, {total:.1f}s")[:300],
        "shots": validated_shots,
        "total": round(total, 3),
        "source": "llm",
    }


def _clamp_joint(value: float, index: int) -> float:
    if not math.isfinite(value):
        raise DirectorPlannerError("Joint values must be finite")
    lo, hi = JOINT_LIMITS[index]
    return round(min(hi, max(lo, value)), 4)
