from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.face_recognition import DEFAULT_FACE_THRESHOLD


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_env_file(path: str | Path = ENV_PATH) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None


def _optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


def _optional_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.lower() in {"1", "true", "yes", "on"}


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be greater than or equal to 1")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _camera_source(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in {"orbbec", "opencv"}:
        raise ValueError(f"{name} must be 'orbbec' or 'opencv'")
    return value


def _director_plan_mode(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in {"llm", "local"}:
        raise ValueError(f"{name} must be 'llm' or 'local'")
    return value


load_env_file()


@dataclass(frozen=True)
class Settings:
    yolo_model: str = os.getenv("YOLO_MODEL", "models/yolo26s.pt")
    yolo_confidence: float = float(os.getenv("YOLO_CONFIDENCE", "0.2"))
    yolo_image_size: int | None = _optional_int("YOLO_IMGSZ")
    yolo_end2end: bool | None = _optional_bool("YOLO_END2END")
    yolo_diagnostic_confidence: float | None = _optional_float("YOLO_DIAGNOSTIC_CONFIDENCE")
    face_model: str = os.getenv("FACE_MODEL", "buffalo_l")
    face_threshold: float = float(os.getenv("FACE_THRESHOLD", str(DEFAULT_FACE_THRESHOLD)))
    face_registry_path: str = os.getenv("FACE_REGISTRY_PATH", str(Path("data") / "face_registry.json"))
    default_camera_source: str = _camera_source("DEFAULT_CAMERA_SOURCE", "orbbec")
    default_camera_index: int = int(os.getenv("DEFAULT_CAMERA_INDEX", "0"))
    camera_run_max_saved_images: int = _positive_int("CAMERA_RUN_MAX_SAVED_IMAGES", 100)
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str | None = os.getenv("LLM_API_KEY")
    llm_model: str | None = os.getenv("LLM_MODEL")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.4"))
    llm_timeout_seconds: float = _positive_float("LLM_TIMEOUT_SECONDS", 45.0)
    director_plan_mode: str = _director_plan_mode("DIRECTOR_PLAN_MODE", "llm")


settings = Settings()
