# Director Vision Tool

Small YOLO-based vision service for robotic camera movement. It detects objects in an image or camera frame and returns a simple aiming command for the robot controller.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Ubuntu:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run API

```powershell
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Aim at a target in an uploaded image:

```powershell
curl -X POST http://127.0.0.1:8000/aim/image -F "target=person" -F "file=@sample.jpg"
```

Robot-side object boxes use a compact contract with the object name plus top-left and bottom-right coordinates:

```powershell
curl -X POST http://127.0.0.1:8000/robot/detect/image -F "file=@images/0001.jpg"
```

To return only one target type, pass `target`:

```powershell
curl -X POST http://127.0.0.1:8000/robot/detect/image -F "target=person" -F "file=@images/0001.jpg"
```

Response shape:

```json
{
  "object_count": 1,
  "objects": [
    {
      "object_name": "person",
      "confidence": 0.94,
      "top_left": {"x": 2, "y": 1115},
      "bottom_right": {"x": 632, "y": 1703}
    }
  ]
}
```

Aim from camera index 0:

```powershell
curl -X POST http://127.0.0.1:8000/aim/camera -H "Content-Type: application/json" -d '{"camera_source":"orbbec","target":"person","camera_index":0,"width":1280,"height":720}'
```

Detect robot-side object boxes from camera index 0:

```powershell
curl -X POST http://127.0.0.1:8000/robot/detect/camera -H "Content-Type: application/json" -d '{"camera_source":"orbbec","target":"person","camera_index":0,"width":1280,"height":720}'
```

Start continuous camera detection and face recognition in the API:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/camera/runs" -H "Content-Type: application/json" --data-raw "{""camera_source"":""orbbec"",""camera_index"":0,""name"":""orbbec_live"",""width"":1280,""height"":720,""interval"":0.1,""targets"":[""person""],""recognize_faces"":true,""auto_register_dynamic"":true}"
```

Check the run status with the returned `run_id`:

```powershell
curl.exe "http://127.0.0.1:8000/camera/runs/RUN_ID"
```

Download the latest annotated frame:

```powershell
curl.exe "http://127.0.0.1:8000/camera/runs/RUN_ID/latest-image" --output latest.jpg
```

Stop the run and release the camera:

```powershell
curl.exe -X DELETE "http://127.0.0.1:8000/camera/runs/RUN_ID"
```

## Face Recognition API

The face recognition flow supports two identity libraries:

- Fixed identities are developer-managed and persisted in `data/face_registry.json`.
- Dynamic identities are created automatically in memory during a run and disappear when the API process or CLI exits.

It uses InsightFace `buffalo_l` by default.

First, upload a panorama or current frame to get selectable face boxes:

```powershell
curl -X POST http://127.0.0.1:8000/faces/candidates -F "file=@images/0001.jpg" -F "annotate=true"
```

Then bind one returned `face_id` to the fixed library with a role such as `male_lead`:

```powershell
curl -X POST http://127.0.0.1:8000/faces/register -H "Content-Type: application/json" -d '{"identity":"male_lead","face_id":"FACE_ID_FROM_CANDIDATES"}'
```

Recognize that identity in later frames:

```powershell
curl -X POST http://127.0.0.1:8000/faces/recognize -F "identity=male_lead" -F "file=@images/0002.jpg" -F "annotate=true"
```

Recognize every registered identity in one image and label the output with names such as `person01` and `person02`:

```powershell
curl -X POST http://127.0.0.1:8000/faces/recognize/all -F "file=@images/0002.jpg" -F "annotate=true"
```

Recognize every registered identity from the live camera:

```powershell
curl -X POST http://127.0.0.1:8000/faces/recognize/camera -H "Content-Type: application/json" -d '{"camera_source":"orbbec","camera_index":0,"width":1280,"height":720,"annotate":true}'
```

Recognize fixed identities and automatically add first-seen unknown faces to the dynamic library as `person01`, `person02`, and so on:

```powershell
curl -X POST http://127.0.0.1:8000/faces/recognize/camera -H "Content-Type: application/json" -d '{"camera_source":"orbbec","camera_index":0,"width":1280,"height":720,"annotate":true,"auto_register_dynamic":true,"dynamic_prefix":"person"}'
```

List registered scene identities:

```powershell
curl http://127.0.0.1:8000/faces/identities
```

Annotated face images are written to `images\output`. If dependencies or model weights are missing, the face endpoints return a clear service error while the YOLO endpoints keep working.

## CLI

```powershell
python vision_cli.py sample.jpg --target person
```

Annotated images are written to `images\output` by default. You can choose the output filename:

```powershell
python vision_cli.py sample.jpg --output annotated.jpg
```

Or disable image output and print JSON only:

```powershell
python vision_cli.py sample.jpg --no-output
```

To see why a target was not found, lower the diagnostic threshold or increase the inference image size:

```powershell
python vision_cli.py sample.jpg --target person --diagnostic-confidence 0.05 --imgsz 1280
```

Useful target-debugging options:

- `--classes`: print the class names supported by the loaded model.
- `--imgsz 1280`: run inference at a larger image size, which can help with small or distant people.
- `--diagnostic-confidence 0.05`: report target detections that were filtered out by the main confidence threshold.
- `--no-end2end`: ask supported YOLO models to use the one-to-many head.

Multiple targets can be checked in one call:

```powershell
python vision_cli.py sample.jpg --target person bottle mouse
```

## Orbbec Camera Test

The Orbbec Gemini 335 should be read through OrbbecSDK, not by guessing an OpenCV camera index. On this machine the SDK sees:

```text
Orbbec Gemini 335
Serial Number: CP0H9530010C
Color stream: 1280x720 @ 30 fps
```

List Orbbec SDK devices:

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --list-orbbec
```

Run one YOLO pass against the live camera:

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source orbbec --camera-index 0 --target person --name orbbec
```

The JSON result prints to the terminal. The raw input frame is written to `images\orbbec\orbbec-00.jpg`, and the annotated frame is written to `images\output\orbbec\orbbec-00.jpg`.

Run repeated detection for 30 seconds, once every 5 seconds:

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source orbbec --camera-index 0 --target person --name orbbec --duration 30 --interval 5
```

This writes numbered frames such as `images\orbbec\orbbec-00.jpg`, `images\orbbec\orbbec-01.jpg`, and matching annotated outputs under `images\output\orbbec`.

To label fixed-library people such as `person01` and `person02` in the CLI output images, first register those identities through the face API, then add `--recognize-faces`:

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source orbbec --camera-index 0 --name orbbec_faces --duration 2 --interval 0.1 --width 1280 --height 720 --recognize-faces
```

The JSON for each sample includes `face_recognition`. If it says `miss_reason: no_registered_identities`, create `data\face_registry.json` by registering faces first.

To maintain a restart-cleared dynamic library during one CLI run, use `--auto-register-faces`:

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source orbbec --camera-index 0 --name orbbec_faces --duration 2 --interval 0.1 --width 1280 --height 720 --auto-register-faces
```

If Orbbec Viewer or another camera app is open, close it first. OrbbecSDK needs exclusive access to the device stream.

If you intentionally want to test a normal UVC/OpenCV camera instead, use `--source opencv` and probe indices:

```powershell
@'
import cv2
for i in range(8):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    ok, frame = cap.read()
    print(i, "ok" if ok else "no frame", None if frame is None else frame.shape)
    cap.release()
'@ | .\.venv\Scripts\python.exe -
```

If model download is interrupted, delete the partial weight file and run again. When using the bundled local model, this should not be needed:

```powershell
Remove-Item .\models\yolo26s.pt
```

## Output Contract

The robot controller should mainly use these fields:

- `found`: whether the target is visible.
- `accepted_labels`: model class names accepted for the requested target.
- `confidence_threshold`: minimum confidence used for this result.
- `image_size`: inference image size passed to YOLO, or `null` for the model default.
- `detection_count`: number of detections returned before target filtering.
- `match_count`: number of detections matching the accepted target labels.
- `labels_seen`: object labels YOLO actually returned at the main confidence threshold.
- `miss_reason`: why `found` is false, such as `no_detections`, `no_matching_labels`, or `only_low_confidence_matches`.
- `low_confidence_matches`: target matches found only below `confidence_threshold` when `--diagnostic-confidence` is used.
- `command`: one of `search`, `hold`, `pan_left`, `pan_right`, `tilt_up`, `tilt_down`.
- `centered`: whether the target is close enough to the frame center.
- `offset_ratio`: target center offset from image center. Positive x means target is on the right, positive y means target is lower.
- `detection.box`: target bounding box as `[x1, y1, x2, y2]`.

For production scenes with named actors, train a custom YOLO model or add a face/person re-identification module. Generic YOLO can detect `person`, but it cannot reliably know which person is the male lead or female lead without extra identity logic.

## Ubuntu Deployment

For a robot-side Ubuntu machine, copy this project directory to the machine and run:

```bash
bash deploy/install_ubuntu.sh
```

The script installs the app into `/opt/director-vision`, creates a `director` service user, installs Python dependencies, and registers a systemd service named `director-vision`.

Useful commands:

```bash
sudo systemctl status director-vision
sudo journalctl -u director-vision -f
curl http://127.0.0.1:8000/health
```

Configuration lives in `/opt/director-vision/.env`:

```bash
YOLO_MODEL=models/yolo26s.pt
YOLO_CONFIDENCE=0.2
FACE_MODEL=buffalo_l
FACE_THRESHOLD=0.45
FACE_REGISTRY_PATH=data/face_registry.json
```

If you train a custom model, put the `.pt` file on the Ubuntu machine and set `YOLO_MODEL=/path/to/best.pt`.
