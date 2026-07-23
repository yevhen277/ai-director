from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

import cv2

from app.config import settings
from app.detector import YoloDetector, draw_detections, load_image
from app.vision import run_yolo_detection


def main() -> None:
    output_dir = Path("images") / "output"
    parser = argparse.ArgumentParser(description="Run YOLO detection or aiming on one image.")
    parser.add_argument("image", help="Path to an image file")
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
    parser.add_argument("--classes", action="store_true", help="Print model class names and exit")
    parser.add_argument(
        "--output",
        nargs="?",
        const="",
        default="",
        help="Write an annotated image with detection boxes. Defaults to images/output/<image>_annotated.<ext>",
    )
    parser.add_argument("--no-output", action="store_true", help="Do not write an annotated image")
    parser.add_argument("--tolerance", type=float, default=0.08, help="Centering tolerance as frame ratio")
    args = parser.parse_args()

    try:
        image = None if args.classes else load_image(args.image)
        detector = YoloDetector(
            model_path=args.model,
            confidence=args.confidence,
            image_size=args.imgsz,
            end2end=args.end2end,
        )
        if args.classes:
            print(json.dumps(detector.class_names, ensure_ascii=False, indent=2))
            return
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    vision_result = run_yolo_detection(
        detector=detector,
        image=image,
        targets=args.target,
        tolerance_ratio=args.tolerance,
        diagnostic_confidence=args.diagnostic_confidence,
    )
    result = vision_result.results
    detections_for_output = vision_result.detections_for_output

    if not args.no_output:
        output_path = _resolve_output_path(args.image, args.output, output_dir)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        annotated = draw_detections(image, detections_for_output)
        if not cv2.imwrite(str(output_path), annotated):
            print(f"Error: could not write annotated image: {output_path}", file=sys.stderr)
            raise SystemExit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _resolve_output_path(image_path: str, output_name: str, output_dir: Path) -> Path:
    image = Path(image_path)
    suffix = image.suffix or ".jpg"
    default_name = f"{image.stem}_annotated{suffix}"

    if not output_name:
        return output_dir / default_name

    output_path = Path(output_name)
    if output_name.endswith(("/", "\\")) or output_path.is_dir():
        return output_path / default_name

    if output_path.suffix:
        return output_dir / output_path.name

    return output_dir / f"{output_path.name}{suffix}"


if __name__ == "__main__":
    main()
