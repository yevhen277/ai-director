# Frontend API Reference

This document collects the API details the frontend needs for `Director Vision Tool`.

Default local base URL:

```text
http://127.0.0.1:8000
```

## Common Rules

- Image upload endpoints use `multipart/form-data`.
- JSON endpoints use `Content-Type: application/json`.
- Image coordinates use the top-left corner as the origin, in pixels.
- `box` format is `[x1, y1, x2, y2]`.
- `frame_size` format is `[width, height]`.
- `offset` is the pixel offset from the frame center to the target center, as `[x, y]`.
- `offset_ratio` is the normalized offset, as `[x_ratio, y_ratio]`. Positive `x` means the target is to the right. Positive `y` means the target is lower in the frame.
- Python tuples are serialized as JSON arrays.

## Error Format

FastAPI returns errors in this shape:

```json
{
  "detail": "error message"
}
```

Common status codes:

| Status | Meaning |
| --- | --- |
| `400` | Uploaded image cannot be read, or request parameters are invalid. |
| `404` | `face_id` is unknown or expired when registering a face. |
| `500` | Camera frame cannot be read, or annotated output image cannot be written. |
| `503` | Face recognition dependency or model is unavailable. |

## Data Types

### Detection

YOLO detection result.

```json
{
  "label": "person",
  "confidence": 0.87,
  "box": [120, 80, 420, 720]
}
```

| Field | Type | Description |
| --- | --- | --- |
| `label` | string | Detected class name. |
| `confidence` | number | Detection confidence, usually between `0` and `1`. |
| `box` | number[] | Bounding box `[x1, y1, x2, y2]`. |

### AimResult

Robot or gimbal aiming result.

```json
{
  "found": true,
  "target": "person",
  "accepted_labels": ["person"],
  "confidence_threshold": 0.2,
  "image_size": null,
  "frame_size": [1280, 720],
  "detection": {
    "label": "person",
    "confidence": 0.87,
    "box": [120, 80, 420, 720]
  },
  "match_count": 1,
  "detection_count": 3,
  "labels_seen": ["person", "chair"],
  "miss_reason": null,
  "low_confidence_matches": [],
  "offset": [-310.0, 40.0],
  "offset_ratio": [-0.2421875, 0.0555555556],
  "command": "pan_left",
  "centered": false
}
```

| Field | Type | Description |
| --- | --- | --- |
| `found` | boolean | Whether the requested target was found. |
| `target` | string | Original requested target text. |
| `accepted_labels` | string[] | YOLO labels accepted for the requested target. |
| `confidence_threshold` | number | Main YOLO confidence threshold used for this result. |
| `image_size` | number, number[], or null | YOLO inference image size. `null` means model default. |
| `frame_size` | number[] | Frame size `[width, height]`. |
| `detection` | Detection or null | Best matching target detection. `null` when not found. |
| `match_count` | number | Count of detections matching `accepted_labels`. |
| `detection_count` | number | Total detections at the main confidence threshold. |
| `labels_seen` | string[] | Labels seen at the main confidence threshold. |
| `miss_reason` | string or null | Reason the target was not found. `null` when found. |
| `low_confidence_matches` | Detection[] | Target detections found only by the diagnostic lower threshold. |
| `offset` | number[] or null | Pixel offset from frame center to target center. |
| `offset_ratio` | number[] or null | Normalized offset from frame center to target center. |
| `command` | string | Suggested movement command. |
| `centered` | boolean | Whether the target is within the tolerance around frame center. |

`command` values:

| Value | Meaning |
| --- | --- |
| `search` | Target was not found. Keep searching. |
| `hold` | Target is centered. Hold position. |
| `pan_left` | Pan left. |
| `pan_right` | Pan right. |
| `tilt_up` | Tilt up. |
| `tilt_down` | Tilt down. |

`miss_reason` values for aiming:

| Value | Meaning |
| --- | --- |
| `no_detections` | No detections at the main threshold. |
| `no_matching_labels` | Detections exist, but none match the requested target labels. |
| `only_low_confidence_matches` | Matching target exists only below the main confidence threshold. |

### FaceCandidate

Temporary selectable face candidate returned by face detection.

```json
{
  "face_id": "c8c69f1e-6b85-4f88-babe-2b7d3e1a1c10",
  "box": [300, 120, 420, 260],
  "confidence": 0.94,
  "center": [360.0, 190.0]
}
```

| Field | Type | Description |
| --- | --- | --- |
| `face_id` | string | Temporary face ID for `/faces/register`. It is kept in memory, expires after about 10 minutes by default, and is lost after service restart. |
| `box` | number[] | Face box `[x1, y1, x2, y2]`. |
| `confidence` | number | Face detection confidence. |
| `center` | number[] | Face box center `[x, y]`. |

### RegisteredFace

Stored identity binding.

```json
{
  "identity": "male_lead",
  "threshold": 0.45,
  "source_image": "scene_001.jpg",
  "source_face_id": "c8c69f1e-6b85-4f88-babe-2b7d3e1a1c10",
  "created_at": 1760000000.123
}
```

| Field | Type | Description |
| --- | --- | --- |
| `identity` | string | Business identity, for example `male_lead` or `female_lead`. |
| `threshold` | number | Default similarity threshold for recognizing this identity. |
| `source_image` | string or null | Optional source image label/path supplied by frontend. |
| `source_face_id` | string or null | Temporary `face_id` used when binding this identity. |
| `created_at` | number | Unix timestamp in seconds. |

### FaceMatch

Recognition result for a requested identity.

```json
{
  "found": true,
  "identity": "male_lead",
  "library": "fixed",
  "threshold": 0.45,
  "similarity": 0.71,
  "face_id": "f86d5dc1-eef3-4f1e-b2b2-6d05c4e9e436",
  "box": [310, 130, 430, 270],
  "frame_size": [1280, 720],
  "offset": [-270.0, -50.0],
  "offset_ratio": [-0.2109375, -0.0694444444],
  "match_count": 1,
  "face_count": 2,
  "miss_reason": null,
  "output_path": "images\\output\\scene_002_male_lead.jpg"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `found` | boolean | Whether the requested identity was recognized. |
| `identity` | string | Requested identity. |
| `library` | string | `fixed` for the persistent developer-managed library, `dynamic` for the restart-cleared runtime library, or `none` when the identity is unknown. |
| `threshold` | number | Similarity threshold used for this recognition. |
| `similarity` | number or null | Best similarity score. `null` when no faces are detected. |
| `face_id` | string or null | Temporary face ID for the recognized face. |
| `box` | number[] or null | Recognized face box. |
| `frame_size` | number[] | Frame size `[width, height]`. |
| `offset` | number[] or null | Pixel offset from frame center to recognized face center. |
| `offset_ratio` | number[] or null | Normalized offset from frame center to recognized face center. |
| `match_count` | number | Count of faces above the threshold. |
| `face_count` | number | Count of faces detected in the image. |
| `miss_reason` | string or null | Reason the identity was not found. |
| `output_path` | string or null | Annotated image path when `annotate=true`; otherwise `null`. |

`FaceMatch.miss_reason` values:

| Value | Meaning |
| --- | --- |
| `identity_not_registered` | The requested identity has not been registered. |
| `no_faces` | No faces were detected in the image. |
| `no_identity_match` | Faces were detected, but none reached the threshold. |

### FaceRecognitionResult

Recognition result for all registered identities in one frame.

```json
{
  "frame_size": [1280, 720],
  "registered_count": 2,
  "fixed_count": 1,
  "dynamic_count": 1,
  "face_count": 2,
  "recognized_count": 2,
  "auto_registered_count": 1,
  "matches": [
    {
      "found": true,
      "identity": "person01",
      "library": "dynamic",
      "similarity": 0.73,
      "box": [310, 130, 430, 270]
    }
  ],
  "unmatched_faces": [],
  "miss_reason": null,
  "output_path": "images\\output\\0002_recognized_faces.jpg"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `registered_count` | number | Total number of fixed and dynamic identities considered. |
| `fixed_count` | number | Number of persistent developer-managed identities considered. |
| `dynamic_count` | number | Number of runtime dynamic identities currently in memory. |
| `face_count` | number | Number of faces detected in the frame. |
| `recognized_count` | number | Number of faces assigned to a registered identity. |
| `auto_registered_count` | number | Number of unmatched faces added to the dynamic library during this request. |
| `matches` | FaceMatch[] | Recognized identities. Each item contains the identity name, similarity, face box, and offset. |
| `unmatched_faces` | FaceCandidate[] | Detected faces that did not match a registered identity. |
| `miss_reason` | string or null | `no_registered_identities`, `no_faces`, or `no_identity_match` when no identity is recognized. |
| `output_path` | string or null | Annotated image path when `annotate=true`; otherwise `null`. |

## Endpoints

### GET /health

Checks whether the service is available.

Request:

```bash
curl http://127.0.0.1:8000/health
```

Response:

```json
{
  "status": "ok",
  "model": "yolo26s.pt",
  "face_model": "buffalo_l"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `status` | string | Service status. Normal value is `ok`. |
| `model` | string | Current YOLO model path. |
| `face_model` | string | Current InsightFace model name. |

### POST /detect/image

Uploads an image and returns all YOLO detections.

Content type: `multipart/form-data`

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | File | Yes | Image file to detect. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/detect/image \
  -F "file=@sample.jpg"
```

Response type: `Detection[]`

Response:

```json
[
  {
    "label": "person",
    "confidence": 0.87,
    "box": [120, 80, 420, 720]
  },
  {
    "label": "chair",
    "confidence": 0.62,
    "box": [700, 330, 900, 710]
  }
]
```

### POST /aim/image

Uploads an image, detects the requested target, and returns movement guidance.

Content type: `multipart/form-data`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `target` | string | Yes | - | Target text, for example `person`, `male_lead`, or `food`. |
| `tolerance_ratio` | number | No | `0.08` | Centering tolerance. If both absolute offset ratios are within this value, `command` is `hold`. |
| `file` | File | Yes | - | Image file to detect. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/aim/image \
  -F "target=person" \
  -F "tolerance_ratio=0.08" \
  -F "file=@sample.jpg"
```

Response type: `AimResult`

Frontend usage:

- Use `found`, `command`, `centered`, `offset_ratio`, and `detection.box` for the main UI/control flow.
- When `found=false`, use `miss_reason` and `labels_seen` for debugging target naming or model output.

### POST /aim/camera

Reads one frame from a camera on the backend machine and returns movement guidance.

Content type: `application/json`

Request body:

```json
{
  "camera_index": 0,
  "target": "person",
  "tolerance_ratio": 0.08
}
```

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `camera_index` | number | No | `0` | Camera index on the backend machine. |
| `target` | string | Yes | - | Target text. |
| `tolerance_ratio` | number | No | `0.08` | Centering tolerance. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/aim/camera \
  -H "Content-Type: application/json" \
  -d '{"camera_index":0,"target":"person","tolerance_ratio":0.08}'
```

Response type: `AimResult`

Camera read failure returns `500`:

```json
{
  "detail": "Could not read camera frame"
}
```

### POST /faces/candidates

Uploads an image, detects faces, and returns candidates that the frontend can display and bind to identities.

Content type: `multipart/form-data`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `file` | File | Yes | - | Image file for face detection. |
| `annotate` | boolean | No | `false` | Whether to create an annotated image with face boxes. |
| `output_name` | string | No | Auto-generated | Annotated image file name. Backend keeps only the file name and writes it under `images/output`. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/faces/candidates \
  -F "file=@images/0001.jpg" \
  -F "annotate=true"
```

Response:

```json
{
  "face_count": 2,
  "faces": [
    {
      "face_id": "c8c69f1e-6b85-4f88-babe-2b7d3e1a1c10",
      "box": [300, 120, 420, 260],
      "confidence": 0.94,
      "center": [360.0, 190.0]
    }
  ],
  "output_path": "images\\output\\0001_faces.jpg"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `face_count` | number | Number of faces detected. |
| `faces` | FaceCandidate[] | Candidate faces. |
| `output_path` | string or null | Annotated image path when `annotate=true`; otherwise `null`. |

Note: `face_id` is temporary and should be used soon in `/faces/register`.

### POST /faces/register

Binds a candidate `face_id` from `/faces/candidates` to a business identity.

Content type: `application/json`

Request body:

```json
{
  "identity": "male_lead",
  "face_id": "c8c69f1e-6b85-4f88-babe-2b7d3e1a1c10",
  "threshold": 0.45,
  "source_image": "images/0001.jpg"
}
```

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `identity` | string | Yes | - | Business identity. Cannot be empty after trimming. |
| `face_id` | string | Yes | - | Temporary face ID returned by `/faces/candidates`. |
| `threshold` | number | No | Backend `FACE_THRESHOLD`, default `0.45` | Default similarity threshold for this identity. |
| `source_image` | string or null | No | `null` | Optional source image label/path for frontend tracking. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/faces/register \
  -H "Content-Type: application/json" \
  -d '{"identity":"male_lead","face_id":"c8c69f1e-6b85-4f88-babe-2b7d3e1a1c10","threshold":0.45}'
```

Response type: `RegisteredFace`

Possible errors:

| Status | Meaning |
| --- | --- |
| `400` | `identity` is empty or another parameter is invalid. |
| `404` | `face_id` is unknown or expired. |

### POST /faces/recognize

Uploads an image and checks whether it contains the requested identity.

Content type: `multipart/form-data`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `identity` | string | Yes | - | Business identity to recognize. |
| `threshold` | number | No | Registered identity threshold | Temporary similarity threshold override for this request. |
| `annotate` | boolean | No | `false` | Whether to create an annotated image with the matched face box. |
| `output_name` | string | No | Auto-generated | Annotated image file name. Backend keeps only the file name and writes it under `images/output`. |
| `file` | File | Yes | - | Image file to recognize. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/faces/recognize \
  -F "identity=male_lead" \
  -F "threshold=0.45" \
  -F "annotate=true" \
  -F "file=@images/0002.jpg"
```

Response type: `FaceMatch` with `output_path`

Frontend usage:

- Use `found` to determine whether the identity was recognized.
- When found, use `box` to draw the face and `offset_ratio` for centering/control.
- When not found, use `miss_reason`, `similarity`, and `face_count` for debugging and user feedback.

### POST /faces/recognize/all

Uploads an image and recognizes all registered identities in the frame. If `annotate=true`, the output image labels recognized faces with the registered identity names, for example `person01` and `person02`.

Content type: `multipart/form-data`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `threshold` | number | No | Registered identity thresholds | Temporary similarity threshold override for all identities in this request. |
| `include_fixed` | boolean | No | `true` | Whether to match the fixed persistent library. |
| `include_dynamic` | boolean | No | `true` | Whether to match the in-memory dynamic library. |
| `auto_register_dynamic` | boolean | No | `false` | Whether to add unmatched faces to the dynamic library as first-seen identities. |
| `dynamic_prefix` | string | No | `person` | Prefix for auto-created dynamic identities, producing names such as `person01`. |
| `annotate` | boolean | No | `false` | Whether to create an annotated image with all recognized face labels. |
| `output_name` | string | No | Auto-generated | Annotated image file name. |
| `file` | File | Yes | - | Image file to recognize. |

Request:

```bash
curl -X POST http://127.0.0.1:8000/faces/recognize/all \
  -F "annotate=true" \
  -F "file=@images/0002.jpg"
```

Response type: `FaceRecognitionResult`

### POST /faces/recognize/camera

Reads one frame from the backend camera and recognizes all registered identities. The default is `annotate=true`, so it writes an output image labeled with names such as `person01` and `person02`.

Content type: `application/json`

Request body:

```json
{
  "camera_source": "orbbec",
  "camera_index": 0,
  "width": 1280,
  "height": 720,
  "threshold": 0.45,
  "include_fixed": true,
  "include_dynamic": true,
  "auto_register_dynamic": true,
  "dynamic_prefix": "person",
  "annotate": true
}
```

Request:

```bash
curl -X POST http://127.0.0.1:8000/faces/recognize/camera \
  -H "Content-Type: application/json" \
  -d '{"camera_source":"orbbec","camera_index":0,"width":1280,"height":720,"annotate":true,"auto_register_dynamic":true}'
```

Response type: `FaceRecognitionResult`

### GET /faces/identities

Returns all registered business identities.

Request:

```bash
curl http://127.0.0.1:8000/faces/identities
```

Response:

```json
{
  "fixed": [
    {
      "identity": "male_lead",
      "threshold": 0.45,
      "source_image": "images/0001.jpg",
      "source_face_id": "c8c69f1e-6b85-4f88-babe-2b7d3e1a1c10",
      "created_at": 1760000000.123
    }
  ],
  "dynamic": []
}
```

## Suggested Frontend Flows

### Target Detection And Control

1. Call `POST /aim/image` with the current frame and `target`.
2. If `found=true`, use `command` for movement and `detection.box` for drawing the target box.
3. If `centered=true` or `command=hold`, the target is within the configured tolerance.
4. If `found=false`, use `miss_reason` to display a useful message or debug model output.

### Face Identity Binding

1. Call `POST /faces/candidates` with a frame that contains people.
2. Draw each returned `faces[].box` as a selectable candidate.
3. Let the user select a face and choose a business identity, for example `male_lead`.
4. Call `POST /faces/register` with the selected `face_id` and `identity`.
5. Later, call `POST /faces/recognize` to recognize that identity in new frames.

## Configuration

These environment variables affect API behavior or recognition quality:

| Variable | Default | Description |
| --- | --- | --- |
| `YOLO_MODEL` | `yolo26s.pt` | YOLO model path. |
| `YOLO_CONFIDENCE` | `0.2` | Main YOLO confidence threshold. |
| `YOLO_IMGSZ` | Not set | YOLO inference image size. |
| `YOLO_END2END` | Not set | Optional YOLO `end2end` prediction flag. |
| `YOLO_DIAGNOSTIC_CONFIDENCE` | Not set | Lower diagnostic threshold used for `low_confidence_matches`. |
| `FACE_MODEL` | `buffalo_l` | InsightFace model name. |
| `FACE_THRESHOLD` | `0.45` | Default face identity similarity threshold. |
| `FACE_REGISTRY_PATH` | `data/face_registry.json` | Face identity registry path. |
