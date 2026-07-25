from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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

PLANNER_STATES = {
    "home": SAFE_POSES["home"],
    "far": SAFE_POSES["far"],
}


class DirectorPlannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlannerInput:
    user_prompt: str
    vision_context: dict[str, Any] | None = None
    image_path: str | Path | None = None
    max_duration_seconds: float = 28.0


def generate_director_plan(planner_input: PlannerInput) -> dict[str, Any]:
    if not settings.llm_api_key:
        raise DirectorPlannerError("LLM_API_KEY is not configured")
    if not settings.llm_model:
        raise DirectorPlannerError("LLM_MODEL is not configured")

    raw_plan = _call_chat_completions(planner_input)
    return _validate_plan(
        raw_plan,
        max_duration_seconds=planner_input.max_duration_seconds,
        vision_context=planner_input.vision_context,
    )


def _call_chat_completions(planner_input: PlannerInput) -> dict[str, Any]:
    user_content: str | list[dict[str, Any]] = _user_prompt(planner_input)
    if planner_input.image_path:
        user_content = [
            {"type": "text", "text": _user_prompt(planner_input)},
            {"type": "image_url", "image_url": {"url": _image_data_url(planner_input.image_path)}},
        ]

    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": _system_prompt(planner_input.max_duration_seconds)},
            {"role": "user", "content": user_content},
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
- The backend will convert your high-level shot timing and TCP state into safe A1Z move commands.

Output schema:
{{
  "title": "short plan title",
  "summary": "1 sentence, include subject and visual intent",
  "shots": [
    {{
      "name": "shot name",
      "tech": "ESTABLISH | FIND | FAR | HOME",
      "desc": "what this shot accomplishes",
      "target": {{
        "source_type": "object | face",
        "identity": "detected object label or face identity",
        "label": "object label, optional for faces",
        "box": [x1,y1,x2,y2],
        "confidence": 0.0
      }},
      "target_intent": "what this shot asks the arm to find or keep in frame",
      "tcp_status": "home | far | find",
      "arm_action": "concrete timing and arm movement, e.g. 0-4s search cup from medium pose then push in",
      "t0": 0.0,
      "t1": 3.0
    }}
  ]
}}

Rules:
- Match the user's language for all human-readable planning text: title, summary, shot name, and desc.
- Keep machine-readable fields unchanged: tech must use only ESTABLISH, FIND, FAR, or HOME. t0/t1 must remain numeric.
- You may receive an actual camera image. Use it to infer scene mood, lighting, subject placement, and whether the user's described subject is present.
- The summary must mention what is actually visible in the image. If the requested subject or mood is not clearly visible, state that uncertainty and plan a cautious establish/search shot.
- Use 2 to 5 shots, total duration <= {max_duration_seconds:.1f} seconds.
- The only allowed robot/TCP states and named robot poses are exactly: "home", "far", and "find".
- Do not mention or output any other robot state, pose, location, shot type, camera move, or posture name such as close, low, top, arc, orbit, surround, circle, sweep, truck, insert, overhead, dolly-in pose, or macro pose.
- Do not create cinematic movement shots such as ARC ORBIT, TOP SHOT, LOW ANGLE, TRUCK SWEEP, DOLLY IN, DOLLY OUT, push-in, pull-out, orbit, circle-around, surround, pan, tilt, or sweep. The arm only supports: find one object/face, move home, move far.
- tcp_status must be exactly one of "home", "far", or "find". Use "find" whenever the shot searches for, locates, finds, or tracks an object/face, even if its tech is FAR or its numeric pose is near far. Use "far" only when the shot explicitly moves the arm from home to far or commands a far position without searching. Otherwise use "home".
- If tcp_status is "home" or "far", target must be null and target_intent must not name a specific object or face.
- If a shot both has a target and says it moves from home to far, tcp_status must be "far", not "find".
- If a shot says "寻找/搜索/定位/find/search/locate chair" or similar, tcp_status must be "find" and target must be the searched object/face, such as chair.
- Each shot may target at most one object or face. The robot arm can search for only one item at a time.
- For every shot, set target to exactly one detected object/face or null. Never include an array of targets.
- If target is not null, source_type must be "object" or "face", identity must exactly match an item in available_targets from the user's JSON. Do not translate, rename, pluralize, summarize, or invent target identities.
- For object targets, target.identity must exactly equal one of available_targets.objects[].identity values, and box must copy that same target's box coordinates.
- For face targets, target.identity must exactly equal one of available_targets.faces[].identity values, and box must copy that same target's box coordinates.
- If the requested subject is not clearly detected, set target to null and make the shot a cautious search/establish shot.
- target_intent and arm_action must be human-readable and match the user's language. arm_action must mention the shot time range and describe only home/far/find actions. Do not describe circling, orbiting, surrounding, sweeping, pushing in, pulling out, high angle, low angle, or any unsupported movement.
- If vision context says no person/face/object is visible, create a cautious search or establish plan and mention the uncertainty.
- If a known face identity is present, make that person the subject.
- Do not invent hardware commands, only return the ShotPlan JSON.
""".strip()


def _user_prompt(planner_input: PlannerInput) -> str:
    output_language = _detect_user_language(planner_input.user_prompt)
    return json.dumps(
        {
            "user_prompt": planner_input.user_prompt,
            "output_language": output_language,
            "language_rule": f"Return title, summary, shot name, and desc in {output_language}, matching the user's prompt language.",
            "vision_context": planner_input.vision_context or {},
            "available_targets": _available_targets(planner_input.vision_context),
            "target_identity_rule": "When shot.target is not null, shot.target.identity must exactly match one available_targets item identity and shot.target.box must copy that item's box. Otherwise use target:null.",
            "image_attached": bool(planner_input.image_path),
        },
        ensure_ascii=False,
        indent=2,
    )


def _detect_user_language(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text or ""):
        return "Chinese"
    if re.search(r"[\u3040-\u30ff]", text or ""):
        return "Japanese"
    if re.search(r"[\uac00-\ud7af]", text or ""):
        return "Korean"
    return "English"


def _available_targets(vision_context: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    context = vision_context if isinstance(vision_context, dict) else {}
    object_items = context.get("detections") or context.get("results") or context.get("objects") or []
    face_recognition = context.get("face_recognition") if isinstance(context.get("face_recognition"), dict) else {}
    face_items = context.get("faces") or face_recognition.get("matches") or []
    return {
        "objects": [_available_object_target(item) for item in object_items if isinstance(item, dict)],
        "faces": [_available_face_target(item) for item in face_items if isinstance(item, dict)],
    }


def _available_object_target(item: dict[str, Any]) -> dict[str, Any]:
    identity = str(item.get("label") or item.get("identity") or item.get("object_name") or "").strip()
    box = _normalize_target_box(item.get("box") or _box_from_robot_object(item))
    target: dict[str, Any] = {
        "source_type": "object",
        "identity": identity,
        "label": identity,
        "box": box,
    }
    confidence = _finite_float(item.get("confidence"))
    if confidence is not None:
        target["confidence"] = max(0.0, min(1.0, confidence))
    return target


def _available_face_target(item: dict[str, Any]) -> dict[str, Any]:
    identity = str(item.get("identity") or item.get("label") or "unknown").strip()
    box = _normalize_target_box(item.get("box"))
    target: dict[str, Any] = {
        "source_type": "face",
        "identity": identity,
        "box": box,
    }
    confidence = _finite_float(item.get("similarity") or item.get("confidence"))
    if confidence is not None:
        target["confidence"] = max(0.0, min(1.0, confidence))
    return target


def _box_from_robot_object(item: dict[str, Any]) -> list[Any] | None:
    top_left = item.get("top_left")
    bottom_right = item.get("bottom_right")
    if not isinstance(top_left, dict) or not isinstance(bottom_right, dict):
        return None
    return [top_left.get("x"), top_left.get("y"), bottom_right.get("x"), bottom_right.get("y")]


def _image_data_url(image_path: str | Path) -> str:
    path = Path(image_path)
    if not path.is_file():
        raise DirectorPlannerError(f"Planner image not found: {path}")
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    import base64

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


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


def _validate_plan(
    plan: dict[str, Any],
    max_duration_seconds: float,
    vision_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shots = plan.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 8:
        raise DirectorPlannerError("Plan must contain 1 to 8 shots")

    allowed_targets = _target_lookup(_available_targets(vision_context))
    validated_shots: list[dict[str, Any]] = []
    last_time = 0.0
    for shot_index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise DirectorPlannerError("Each shot must be an object")
        keyframes = shot.get("keyframes")
        if not isinstance(keyframes, list):
            keyframes = []
        if len(keyframes) < 2:
            previous_pose = validated_shots[-1]["keyframes"][-1][0] if validated_shots else SAFE_POSES["home"]
            keyframes = _repair_short_keyframes(
                keyframes=keyframes,
                shot=shot,
                shot_index=shot_index,
                last_time=last_time,
                previous_pose=previous_pose,
                max_duration_seconds=max_duration_seconds,
            )

        validated_keyframes = []
        for frame in keyframes:
            if not isinstance(frame, list | tuple) or len(frame) != 2:
                raise DirectorPlannerError("Each keyframe must be [[q1..q6], t]")
            q, t = frame
            if isinstance(q, str) and q in SAFE_POSES:
                q = SAFE_POSES[q]
            if not isinstance(q, list | tuple) or len(q) != 6:
                raise DirectorPlannerError("Each keyframe pose must contain exactly 6 joints")
            q_validated = [_clamp_joint(float(value), i) for i, value in enumerate(q)]
            t_value = float(t)
            if not math.isfinite(t_value):
                raise DirectorPlannerError("Keyframe time must be finite")
            if validated_keyframes and t_value < validated_keyframes[-1][1]:
                t_value = validated_keyframes[-1][1] + 0.8
            validated_keyframes.append([q_validated, round(t_value, 3)])

        if shot_index == 0 and validated_keyframes[0][1] != 0:
            offset = validated_keyframes[0][1]
            validated_keyframes = [[q, round(max(0.0, t - offset), 3)] for q, t in validated_keyframes]
        if validated_keyframes[0][1] < last_time - 0.001:
            offset = last_time - validated_keyframes[0][1]
            validated_keyframes = [[q, round(t + offset, 3)] for q, t in validated_keyframes]
        elif shot_index > 0 and validated_keyframes[0][1] > last_time + 0.001:
            previous_pose = validated_shots[-1]["keyframes"][-1][0]
            validated_keyframes.insert(0, [previous_pose, round(last_time, 3)])

        t0 = validated_keyframes[0][1]
        t1 = validated_keyframes[-1][1]
        if t1 <= t0:
            raise DirectorPlannerError("Shot duration must be positive")
        last_time = t1
        tcp_status = _normalize_tcp_status(shot, validated_keyframes)
        target = _normalize_shot_target(shot.get("target")) if tcp_status == "find" else None
        target = _target_from_lookup(target, allowed_targets)
        validated_shots.append(
            {
                "name": str(shot.get("name") or f"Shot {shot_index + 1}")[:80],
                "tech": _tech_for_tcp_status(shot, tcp_status),
                "desc": str(shot.get("desc") or "")[:240],
                "target": target,
                "target_intent": str(shot.get("target_intent") or "")[:180],
                "tcp_status": tcp_status,
                "arm_action": str(shot.get("arm_action") or "")[:260],
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


def _repair_short_keyframes(
    *,
    keyframes: list[Any],
    shot: dict[str, Any],
    shot_index: int,
    last_time: float,
    previous_pose: list[float],
    max_duration_seconds: float,
) -> list[Any]:
    duration = _fallback_duration(shot, last_time, max_duration_seconds)
    end_time = round(last_time + duration, 3)
    tech = str(shot.get("tech") or "")
    target_pose = _pose_for_tech(tech, shot_index)

    if keyframes and _is_keyframe_like(keyframes[0]):
        q, t = keyframes[0]
        if isinstance(q, str) and q in SAFE_POSES:
            q = SAFE_POSES[q]
        t_value = _finite_float(t)
        if t_value is not None and t_value > last_time + 0.05:
            return [[previous_pose, last_time], [q, t_value]]
        return [[q, last_time], [target_pose, end_time]]

    return [[previous_pose, last_time], [target_pose, end_time]]


def _fallback_duration(shot: dict[str, Any], last_time: float, max_duration_seconds: float) -> float:
    raw_t1 = _finite_float(shot.get("t1"))
    if raw_t1 is not None and raw_t1 > last_time + 0.4:
        return max(0.8, min(5.0, raw_t1 - last_time))
    remaining = max_duration_seconds - last_time
    return max(0.8, min(3.5, remaining if remaining > 0 else 0.8))


def _pose_for_tech(tech: str, shot_index: int) -> list[float]:
    upper = tech.upper()
    if "DOLLY" in upper or "CLOSE" in upper:
        return SAFE_POSES["close"]
    if "ARC" in upper:
        return SAFE_POSES["orbL1" if shot_index % 2 else "orbR1"]
    if "TOP" in upper:
        return SAFE_POSES["top"]
    if "LOW" in upper:
        return SAFE_POSES["lowPre"]
    if "TRUCK" in upper or "SWEEP" in upper:
        return SAFE_POSES["swpA" if shot_index % 2 else "swpB"]
    if "RECOVER" in upper or "FINAL" in upper:
        return SAFE_POSES["home"]
    return SAFE_POSES["far" if shot_index == 0 else "home"]


def _normalize_tech(shot: dict[str, Any], keyframes: list[list[Any]]) -> str:
    return _tech_for_tcp_status(shot, _normalize_tcp_status(shot, keyframes))


def _tech_for_tcp_status(shot: dict[str, Any], status: str) -> str:
    if status == "far":
        return "FAR"
    if status == "find":
        return "FIND"
    raw_tech = str(shot.get("tech") or "").strip().upper()
    if raw_tech == "ESTABLISH":
        return "ESTABLISH"
    return "HOME"


def _normalize_tcp_status(shot: dict[str, Any], keyframes: list[list[Any]]) -> str:
    raw_status = str(shot.get("tcp_status") or shot.get("state") or "").strip().lower()
    text = " ".join(
        str(shot.get(field) or "")
        for field in ("name", "tech", "desc", "target_intent", "arm_action")
    ).lower()
    target = _normalize_shot_target(shot.get("target"))

    if _text_mentions_far_destination(text):
        return "far"
    if _text_mentions_search_intent(text) or raw_status == "find" or target is not None:
        return "find"
    if raw_status == "far" or _last_pose_is_far(keyframes):
        return "far"
    if raw_status == "home":
        return "home"
    return "home"


def _text_mentions_far_destination(text: str) -> bool:
    return bool(
        re.search(r"\b(to|toward|towards|into|end(?:s|ing)?\s+at|move(?:s|ing)?\s+to)\s+(?:the\s+)?far\b", text)
        or re.search(r"\bhome\b.*\bfar\b", text)
        or re.search(r"\u4ece\s*home\s*(?:\u4f4d\u7f6e)?\s*(?:\u7f13\u6162)?(?:\u79fb\u52a8|\u8fd0\u52a8|\u5230|\u81f3).*far\s*(?:\u4f4d\u7f6e)?", text)
        or re.search(r"\u5230\s*far\s*(?:\u4f4d\u7f6e|\u72b6\u6001)?", text)
    )


def _text_mentions_search_intent(text: str) -> bool:
    return bool(
        re.search(r"\b(find|search|locate|track)\b", text)
        or re.search(r"\u5bfb\u627e|\u641c\u7d22|\u5b9a\u4f4d|\u627e\u5230", text)
    )


def _last_pose_is_far(keyframes: list[list[Any]]) -> bool:
    if not keyframes:
        return False
    q = keyframes[-1][0]
    if not isinstance(q, list | tuple) or len(q) != 6:
        return False
    return sum(abs(float(value) - SAFE_POSES["far"][index]) for index, value in enumerate(q)) < 0.08


def _is_keyframe_like(frame: Any) -> bool:
    return isinstance(frame, list | tuple) and len(frame) == 2


def _target_lookup(available_targets: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for source_type, group in (("object", "objects"), ("face", "faces")):
        for target in available_targets.get(group, []):
            normalized = _normalize_shot_target(target)
            if normalized is None:
                continue
            lookup[(source_type, normalized["identity"])] = normalized
    return lookup


def _target_from_lookup(
    target: dict[str, Any] | None,
    allowed_targets: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if target is None:
        return None
    matched = allowed_targets.get((target["source_type"], target["identity"]))
    if matched is None:
        return None
    return matched.copy()


def _normalize_shot_target(target: Any) -> dict[str, Any] | None:
    if not isinstance(target, dict):
        return None

    source_type = str(target.get("source_type") or "").strip().lower()
    if source_type not in {"object", "face"}:
        return None

    identity = str(target.get("identity") or "").strip()
    if not identity:
        return None

    box = _normalize_target_box(target.get("box"))
    if box is None:
        return None

    normalized: dict[str, Any] = {
        "source_type": source_type,
        "identity": identity[:120],
        "box": box,
    }
    label = str(target.get("label") or "").strip()
    if label:
        normalized["label"] = label[:120]
    confidence = _finite_float(target.get("confidence"))
    if confidence is not None:
        normalized["confidence"] = max(0.0, min(1.0, confidence))
    return normalized


def _normalize_target_box(box: Any) -> list[int] | None:
    if not isinstance(box, list | tuple) or len(box) != 4:
        return None
    values: list[int] = []
    for value in box:
        number = _finite_float(value)
        if number is None:
            return None
        values.append(int(round(number)))
    return values


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp_joint(value: float, index: int) -> float:
    if not math.isfinite(value):
        raise DirectorPlannerError("Joint values must be finite")
    lo, hi = JOINT_LIMITS[index]
    return round(min(hi, max(lo, value)), 4)
