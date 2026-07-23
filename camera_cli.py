from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import cv2

from app.camera import OpenCVCamera, OrbbecColorCamera, list_orbbec_devices
from app.config import settings
from app.detector import YoloDetector, draw_detections
from app.vision import run_yolo_detection


def main() -> None:
    image_dir = Path("images")
    output_dir = Path("images") / "output"
    parser = argparse.ArgumentParser(description="Capture one camera frame and run YOLO detection or aiming.")
    parser.add_argument("--source", choices=["orbbec", "opencv"], default="orbbec", help="Camera source backend")
    parser.add_argument("--list-orbbec", action="store_true", help="List Orbbec SDK devices and exit")
    parser.add_argument("--camera-index", type=int, default=0, help="Orbbec device index or OpenCV camera index")
    parser.add_argument("--width", type=int, default=1280, help="Requested capture width")
    parser.add_argument("--height", type=int, default=720, help="Requested capture height")
    parser.add_argument("--fps", type=int, default=30, help="Requested Orbbec color stream FPS")
    parser.add_argument("--warmup", type=int, default=5, help="Frames to discard before inference")
    parser.add_argument("--duration", type=float, default=0, help="Total detection time in seconds. 0 captures once.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between captures when duration is set")
    parser.add_argument("--model-warmup", type=int, default=1, help="Unsaved YOLO warmup frames before timed capture")
    parser.add_argument(
        "--target",
        nargs="+",
        help="One or more target labels or aliases, e.g. person bottle mouse",
    )
    parser.add_argument("--model", default=settings.yolo_model, help="YOLO model path")
    parser.add_argument("--confidence", type=float, default=settings.yolo_confidence, help="Minimum detection confidence")
    parser.add_argument(
        "--imgsz",
        type=int,
        default=settings.yolo_image_size,
        help="YOLO inference image size, e.g. 960 or 1280",
    )
    parser.add_argument(
        "--diagnostic-confidence",
        type=float,
        default=settings.yolo_diagnostic_confidence,
        help="Lower confidence used only to report filtered-out target matches",
    )
    parser.add_argument(
        "--end2end",
        dest="end2end",
        action="store_true",
        default=settings.yolo_end2end,
        help="Force YOLO end-to-end one-to-one prediction head when supported",
    )
    parser.add_argument(
        "--no-end2end",
        dest="end2end",
        action="store_false",
        help="Use YOLO one-to-many prediction head when supported",
    )
    parser.add_argument(
        "--output",
        nargs="?",
        const="",
        help="Run folder/base name for saved input/output images.",
    )
    parser.add_argument("--name", help="Run name, e.g. test001 writes images/test001/test001-00.jpg")
    parser.add_argument("--no-output", action="store_true", help="Do not write an annotated output image")
    parser.add_argument("--tolerance", type=float, default=0.08, help="Centering tolerance as frame ratio")
    args = parser.parse_args()

    if args.list_orbbec:
        try:
            print(json.dumps({"devices": list_orbbec_devices()}, ensure_ascii=False, indent=2))
            return
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    try:
        if args.duration < 0:
            raise ValueError("--duration must be greater than or equal to 0")
        if args.interval <= 0:
            raise ValueError("--interval must be greater than 0")
        detector = YoloDetector(
            model_path=args.model,
            confidence=args.confidence,
            image_size=args.imgsz,
            end2end=args.end2end,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    sample_count = _sample_count(duration=args.duration, interval=args.interval)
    samples = []

    try:
        with _open_camera(args.source, args.camera_index, args.width, args.height, args.fps, args.warmup) as camera:
            for _ in range(max(0, args.model_warmup)):
                warmup_frame = camera.read()
                run_yolo_detection(
                    detector=detector,
                    image=warmup_frame,
                    targets=args.target,
                    tolerance_ratio=args.tolerance,
                    diagnostic_confidence=args.diagnostic_confidence,
                )

            start_time = time.monotonic()
            for sample_index in range(sample_count):
                due_time = start_time + sample_index * args.interval
                sleep_for = due_time - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)

                frame = camera.read()
                input_path, output_path = _resolve_image_paths(
                    name=args.name,
                    output_name=args.output,
                    source=args.source,
                    image_dir=image_dir,
                    output_dir=output_dir,
                    sample_index=sample_index,
                )
                sample = _run_sample(
                    detector=detector,
                    frame=frame,
                    input_path=input_path,
                    output_path=output_path,
                    no_output=args.no_output,
                    targets=args.target,
                    tolerance_ratio=args.tolerance,
                    diagnostic_confidence=args.diagnostic_confidence,
                )
                sample["index"] = sample_index
                sample["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
                samples.append(sample)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    result = {
        "sample_count": len(samples),
        "duration_seconds": args.duration,
        "interval_seconds": args.interval,
        "actual_fps": _actual_fps(samples),
        "samples": samples,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


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


def _run_sample(
    detector: YoloDetector,
    frame,
    input_path: Path,
    output_path: Path,
    no_output: bool,
    targets: list[str] | None,
    tolerance_ratio: float,
    diagnostic_confidence: float | None,
) -> dict:
    input_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(input_path), frame):
        raise RuntimeError(f"could not write input image: {input_path}")

    vision_result = run_yolo_detection(
        detector=detector,
        image=frame,
        targets=targets,
        tolerance_ratio=tolerance_ratio,
        diagnostic_confidence=diagnostic_confidence,
    )

    if not no_output:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        annotated = draw_detections(frame, vision_result.detections_for_output)
        if not cv2.imwrite(str(output_path), annotated):
            raise RuntimeError(f"could not write annotated image: {output_path}")

    return {
        "input_path": str(input_path),
        "output_path": None if no_output else str(output_path),
        "results": vision_result.results,
    }


def _sample_count(duration: float, interval: float) -> int:
    if duration <= 0:
        return 1
    return math.floor(duration / interval + 1e-9) + 1


def _actual_fps(samples: list[dict]) -> float | None:
    if len(samples) < 2:
        return None
    elapsed = samples[-1]["elapsed_seconds"] - samples[0]["elapsed_seconds"]
    if elapsed <= 0:
        return None
    return round((len(samples) - 1) / elapsed, 2)


def _resolve_image_paths(
    name: str | None,
    output_name: str | None,
    source: str,
    image_dir: Path,
    output_dir: Path,
    sample_index: int,
) -> tuple[Path, Path]:
    base_name = name or _stem_from_output_name(output_name) or source
    run_name = _clean_run_name(base_name)
    image_name = _with_frame_suffix(run_name, sample_index)
    return image_dir / run_name / f"{image_name}.jpg", output_dir / run_name / f"{image_name}.jpg"


def _stem_from_output_name(output_name: str | None) -> str | None:
    if output_name is None or output_name == "":
        return None
    return Path(output_name).stem


def _with_frame_suffix(stem: str, sample_index: int) -> str:
    clean_stem = stem[:-3] if len(stem) >= 3 and stem[-3] == "-" and stem[-2:].isdigit() else stem
    return f"{clean_stem}-{sample_index:02d}"


def _clean_run_name(name: str) -> str:
    clean_name = Path(name).stem
    clean_name = clean_name[:-3] if len(clean_name) >= 3 and clean_name[-3] == "-" and clean_name[-2:].isdigit() else clean_name
    if not clean_name:
        raise RuntimeError("run name cannot be empty")
    return clean_name


if __name__ == "__main__":
    main()
