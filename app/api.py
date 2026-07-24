from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

import cv2
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.camera import capture_opencv_frame, capture_orbbec_color_frame, list_orbbec_devices
from app.camera_runs import (
    CameraRunConfig,
    CameraRunConflictError,
    CameraRunManager,
    CameraRunNotFoundError,
    CameraRunValidationError,
)
from app.config import settings
from app.detector import YoloDetector, load_image
from app.director_planner import DirectorPlannerError, PlannerInput, generate_director_plan
from app.face_recognition import (
    FaceRecognitionService,
    candidate_to_dict,
    draw_face_match,
    draw_face_matches,
    draw_faces,
    match_to_dict,
    recognition_result_to_dict,
    registered_to_dict,
)
from app.labels import resolve_target_classes
from app.vision import run_yolo_detection


OUTPUT_DIR = Path("images") / "output"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DIRECTORX_HTML = Path(__file__).resolve().parent.parent / "robot_dog" / "directorx.html"

app = FastAPI(title="Director Vision Tool", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
detector = YoloDetector(
    model_path=settings.yolo_model,
    confidence=settings.yolo_confidence,
    image_size=settings.yolo_image_size,
    end2end=settings.yolo_end2end,
)
face_service = FaceRecognitionService(
    registry_path=settings.face_registry_path,
    model_name=settings.face_model,
)
camera_run_manager = CameraRunManager(detector=detector, face_service=face_service)


class CameraAimRequest(BaseModel):
    camera_source: Literal["orbbec", "opencv"] = settings.default_camera_source
    camera_index: int = settings.default_camera_index
    target: str
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup: int = 5
    tolerance_ratio: float = 0.08


class CameraDetectRequest(BaseModel):
    camera_source: Literal["orbbec", "opencv"] = settings.default_camera_source
    camera_index: int = settings.default_camera_index
    target: str | None = None
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup: int = 5
    tolerance_ratio: float = 0.08


class FaceRegisterRequest(BaseModel):
    identity: str
    face_id: str
    threshold: float = settings.face_threshold
    source_image: str | None = None


class CameraFaceRecognizeRequest(BaseModel):
    camera_source: Literal["orbbec", "opencv"] = settings.default_camera_source
    camera_index: int = settings.default_camera_index
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup: int = 5
    threshold: float | None = None
    include_fixed: bool = True
    include_dynamic: bool = True
    auto_register_dynamic: bool = False
    dynamic_prefix: str = "person"
    annotate: bool = True
    output_name: str | None = None


class CameraRunStartRequest(BaseModel):
    camera_source: Literal["orbbec", "opencv"] = settings.default_camera_source
    camera_index: int = settings.default_camera_index
    name: str | None = None
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup: int = 5
    interval: float = 0.1
    targets: list[str] | None = None
    tolerance_ratio: float = 0.08
    recognize_faces: bool = True
    include_fixed: bool = True
    include_dynamic: bool = True
    auto_register_dynamic: bool = True
    dynamic_prefix: str = "person"
    face_threshold: float | None = None
    max_saved_images: int = settings.camera_run_max_saved_images
    replace_existing: bool = True


class DirectorPlanRequest(BaseModel):
    user_prompt: str
    vision_context: dict | None = None
    max_duration_seconds: float = 28.0


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/directorx")
def directorx():
    if not DIRECTORX_HTML.is_file():
        raise HTTPException(status_code=404, detail=f"DirectorX page not found: {DIRECTORX_HTML}")
    return FileResponse(DIRECTORX_HTML)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "model": settings.yolo_model,
        "face_model": settings.face_model,
        "default_camera_source": settings.default_camera_source,
        "default_camera_index": str(settings.default_camera_index),
        "camera_run_max_saved_images": str(settings.camera_run_max_saved_images),
    }


@app.post("/director/plan")
def director_plan(request: DirectorPlanRequest) -> dict:
    try:
        return generate_director_plan(
            PlannerInput(
                user_prompt=request.user_prompt,
                vision_context=request.vision_context,
                max_duration_seconds=request.max_duration_seconds,
            )
        )
    except DirectorPlannerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/camera/orbbec/devices")
def orbbec_devices() -> dict:
    try:
        return {"devices": list_orbbec_devices()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/camera/runs")
def start_camera_run(request: CameraRunStartRequest) -> dict:
    config = CameraRunConfig(
        camera_source=request.camera_source,
        camera_index=request.camera_index,
        name=request.name,
        width=request.width,
        height=request.height,
        fps=request.fps,
        warmup=request.warmup,
        interval=request.interval,
        targets=request.targets,
        tolerance_ratio=request.tolerance_ratio,
        diagnostic_confidence=settings.yolo_diagnostic_confidence,
        recognize_faces=request.recognize_faces,
        include_fixed=request.include_fixed,
        include_dynamic=request.include_dynamic,
        auto_register_dynamic=request.auto_register_dynamic,
        dynamic_prefix=request.dynamic_prefix,
        face_threshold=request.face_threshold,
        max_saved_images=request.max_saved_images,
    )
    try:
        run = camera_run_manager.start_run(config, replace_existing=request.replace_existing)
    except CameraRunValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CameraRunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run.to_dict()


@app.get("/camera/runs/{run_id}")
def camera_run_status(run_id: str) -> dict:
    try:
        return camera_run_manager.get_run(run_id).to_dict()
    except CameraRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown camera run: {run_id}") from exc


@app.get("/camera/runs/{run_id}/frames")
def camera_run_frames(run_id: str, limit: int = Query(50, ge=1, le=500)) -> dict:
    try:
        return {
            "run_id": run_id,
            "frames": camera_run_manager.recent_frames(run_id=run_id, limit=limit),
        }
    except CameraRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown camera run: {run_id}") from exc


@app.get("/camera/runs/{run_id}/latest-image")
def camera_run_latest_image(run_id: str):
    try:
        output_path = camera_run_manager.latest_output_path(run_id)
    except CameraRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown camera run: {run_id}") from exc
    if output_path is None or not output_path.is_file():
        raise HTTPException(status_code=404, detail=f"No output image is available for camera run: {run_id}")
    return FileResponse(path=str(output_path), media_type="image/jpeg", filename=output_path.name)


@app.delete("/camera/runs/{run_id}")
def stop_camera_run(run_id: str) -> dict:
    try:
        return camera_run_manager.stop_run(run_id)
    except CameraRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown camera run: {run_id}") from exc


@app.post("/detect/image")
async def detect_image(file: UploadFile = File(...)) -> list[dict]:
    image = await _read_upload(file)
    return run_yolo_detection(detector=detector, image=image).results


@app.post("/robot/detect/image")
async def robot_detect_image(
    file: UploadFile = File(...),
    target: str | None = Form(None),
) -> dict:
    image = await _read_upload(file)
    detections = detector.detect(image)
    if target:
        accepted_labels = set(resolve_target_classes(target))
        detections = [detection for detection in detections if detection.label in accepted_labels]

    return {
        "object_count": len(detections),
        "objects": [_robot_object_from_detection(detection) for detection in detections],
    }


@app.post("/robot/detect/camera")
def robot_detect_camera(request: CameraDetectRequest) -> dict:
    frame = _read_camera_frame(
        camera_source=request.camera_source,
        camera_index=request.camera_index,
        width=request.width,
        height=request.height,
        fps=request.fps,
        warmup=request.warmup,
    )
    vision_result = run_yolo_detection(
        detector=detector,
        image=frame,
        targets=[request.target] if request.target else None,
        tolerance_ratio=request.tolerance_ratio,
        diagnostic_confidence=settings.yolo_diagnostic_confidence,
    )
    detections = vision_result.detections_for_output

    return {
        "object_count": len(detections),
        "objects": [_robot_object_from_detection(detection) for detection in detections],
    }


@app.post("/aim/image")
async def aim_image(
    target: str = Form(...),
    tolerance_ratio: float = Form(0.08),
    file: UploadFile = File(...),
) -> dict:
    image = await _read_upload(file)
    return run_yolo_detection(
        detector=detector,
        image=image,
        targets=[target],
        tolerance_ratio=tolerance_ratio,
        diagnostic_confidence=settings.yolo_diagnostic_confidence,
    ).results[0]


@app.post("/aim/camera")
def aim_camera(request: CameraAimRequest) -> dict:
    frame = _read_camera_frame(
        camera_source=request.camera_source,
        camera_index=request.camera_index,
        width=request.width,
        height=request.height,
        fps=request.fps,
        warmup=request.warmup,
    )

    return run_yolo_detection(
        detector=detector,
        image=frame,
        targets=[request.target],
        tolerance_ratio=request.tolerance_ratio,
        diagnostic_confidence=settings.yolo_diagnostic_confidence,
    ).results[0]


@app.post("/faces/candidates")
async def face_candidates(
    file: UploadFile = File(...),
    annotate: bool = Form(False),
    output_name: str | None = Form(None),
) -> dict:
    image = await _read_upload(file)
    try:
        candidates = face_service.detect_faces(image)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    output_path = None
    if annotate:
        output_path = _write_output_image(
            draw_faces(image, candidates),
            output_name or _default_output_name(file.filename, "faces"),
        )

    return {
        "face_count": len(candidates),
        "faces": [candidate_to_dict(candidate) for candidate in candidates],
        "output_path": output_path,
    }


@app.post("/faces/register")
def register_face(request: FaceRegisterRequest) -> dict:
    try:
        registered = face_service.register_candidate(
            identity=request.identity,
            face_id=request.face_id,
            threshold=request.threshold,
            source_image=request.source_image,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return registered_to_dict(registered)


@app.post("/faces/recognize")
async def recognize_face(
    identity: str = Form(...),
    threshold: float | None = Form(None),
    annotate: bool = Form(False),
    output_name: str | None = Form(None),
    file: UploadFile = File(...),
) -> dict:
    image = await _read_upload(file)
    try:
        match = face_service.recognize_identity(
            image=image,
            identity=identity,
            threshold=threshold,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    output_path = None
    if annotate:
        output_path = _write_output_image(
            draw_face_match(image, match),
            output_name or _default_output_name(file.filename, identity),
        )

    result = match_to_dict(match)
    result["output_path"] = output_path
    return result


@app.post("/faces/recognize/all")
async def recognize_all_faces(
    threshold: float | None = Form(None),
    include_fixed: bool = Form(True),
    include_dynamic: bool = Form(True),
    auto_register_dynamic: bool = Form(False),
    dynamic_prefix: str = Form("person"),
    annotate: bool = Form(False),
    output_name: str | None = Form(None),
    file: UploadFile = File(...),
) -> dict:
    image = await _read_upload(file)
    return _recognize_registered_faces(
        image=image,
        threshold=threshold,
        include_fixed=include_fixed,
        include_dynamic=include_dynamic,
        auto_register_dynamic=auto_register_dynamic,
        dynamic_prefix=dynamic_prefix,
        annotate=annotate,
        output_name=output_name or _default_output_name(file.filename, "recognized_faces"),
    )


@app.post("/faces/recognize/camera")
def recognize_all_faces_from_camera(request: CameraFaceRecognizeRequest) -> dict:
    frame = _read_camera_frame(
        camera_source=request.camera_source,
        camera_index=request.camera_index,
        width=request.width,
        height=request.height,
        fps=request.fps,
        warmup=request.warmup,
    )
    return _recognize_registered_faces(
        image=frame,
        threshold=request.threshold,
        include_fixed=request.include_fixed,
        include_dynamic=request.include_dynamic,
        auto_register_dynamic=request.auto_register_dynamic,
        dynamic_prefix=request.dynamic_prefix,
        annotate=request.annotate,
        output_name=request.output_name or f"{request.camera_source}_recognized_faces.jpg",
    )


@app.get("/faces/identities")
def face_identities() -> dict:
    return {
        "fixed": face_service.identities(),
        "dynamic": face_service.dynamic_identities(),
    }


@app.delete("/faces/dynamic/identities")
def clear_dynamic_face_identities() -> dict:
    return {"cleared": face_service.clear_dynamic_identities()}


async def _read_upload(file: UploadFile):
    suffix = os.path.splitext(file.filename or "upload.jpg")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        return load_image(tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _read_camera_frame(camera_source: str, camera_index: int, width: int, height: int, fps: int, warmup: int):
    try:
        if camera_source == "orbbec":
            return capture_orbbec_color_frame(
                device_index=camera_index,
                width=width,
                height=height,
                fps=fps,
                warmup=warmup,
            )
        if camera_source == "opencv":
            return capture_opencv_frame(camera_index=camera_index, width=width, height=height, warmup=warmup)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail=f"Unsupported camera_source: {camera_source}")


def _write_output_image(image, output_name: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / Path(output_name).name
    if not cv2.imwrite(str(output_path), image):
        raise HTTPException(status_code=500, detail=f"Could not write output image: {output_path}")
    return str(output_path)


def _recognize_registered_faces(
    image,
    threshold: float | None,
    include_fixed: bool,
    include_dynamic: bool,
    auto_register_dynamic: bool,
    dynamic_prefix: str,
    annotate: bool,
    output_name: str,
) -> dict:
    try:
        recognition_result = face_service.recognize_registered_identities(
            image=image,
            threshold=threshold,
            include_fixed=include_fixed,
            include_dynamic=include_dynamic,
            auto_register_dynamic=auto_register_dynamic,
            dynamic_prefix=dynamic_prefix,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = recognition_result_to_dict(recognition_result)
    result["output_path"] = None
    if annotate:
        result["output_path"] = _write_output_image(
            draw_face_matches(image, recognition_result.matches),
            output_name,
        )
    return result


def _default_output_name(filename: str | None, suffix: str) -> str:
    image_path = Path(filename or "upload.jpg")
    image_suffix = image_path.suffix or ".jpg"
    return f"{image_path.stem}_{suffix}{image_suffix}"


def _robot_object_from_detection(detection) -> dict:
    x1, y1, x2, y2 = detection.box
    return {
        "object_name": detection.label,
        "confidence": detection.confidence,
        "top_left": {"x": x1, "y": y1},
        "bottom_right": {"x": x2, "y": y2},
    }
