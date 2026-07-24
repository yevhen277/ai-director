# Ubuntu 持续实时相机检测与人脸识别使用指南

这份文档说明如何在 Ubuntu 上启动 API，持续读取相机画面，执行 YOLO 物体检测和人脸识别，并查看标注图片、物体名字和框坐标。

默认服务地址：

```text
http://127.0.0.1:8000
```

## 1. 准备项目

进入项目目录：

```bash
cd director111
```

安装系统依赖和 Python 依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip libgl1 libglib2.0-0 curl

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

如果使用 Orbbec 相机，还需要安装 Orbbec Python SDK。当前代码使用 `pyorbbecsdk` 读取 Orbbec 彩色流。如果没有装好，接口会提示类似：

```text
pyorbbecsdk2 is not installed
```

启动检测前，请关闭 Orbbec Viewer 或其他占用相机的软件。

## 2. 配置模型

项目默认读取 `.env`。如果没有 `.env`，可以复制示例：

```bash
cp .env.example .env
```

常用配置：

```bash
YOLO_MODEL=models/yolo26s.pt
YOLO_CONFIDENCE=0.2
FACE_MODEL=buffalo_l
FACE_THRESHOLD=0.45
FACE_REGISTRY_PATH=data/face_registry.json
```

说明：

- `YOLO_MODEL` 是 YOLO 模型文件路径。
- `FACE_MODEL` 默认是 InsightFace 的 `buffalo_l`。
- `FACE_REGISTRY_PATH` 是固定人脸库保存位置。
- 动态人脸库只在内存里，API 服务重启后自动清空。

## 3. 启动 API 服务

开发方式启动：

```bash
source .venv/bin/activate
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

如果只在本机使用，也可以：

```bash
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

检查服务是否正常：

```bash
curl http://127.0.0.1:8000/health
```

正常会返回类似：

```json
{
  "status": "ok",
  "model": "models/yolo26s.pt",
  "face_model": "buffalo_l"
}
```

## 4. 启动持续实时检测

调用 `POST /camera/runs` 会启动一个后台任务。这个任务会一直读取相机画面，持续执行：

1. YOLO 物体检测
2. 固定人脸库识别
3. 动态人脸库识别
4. 首次看到陌生人脸时自动注册为 `person01`、`person02`
5. 保存原始图片和标注图片

默认只保留最新 `100` 帧图片。超过 100 后，更早的原始图片和标注图片会自动删除，避免硬盘一直增长。

### Orbbec 相机启动命令

这条命令会启动检测，并把返回的 `run_id` 自动保存到当前终端的 `runId` 变量里：

```bash
runResponse=$(curl -s -X POST "http://127.0.0.1:8000/camera/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "camera_source": "orbbec",
    "camera_index": 0,
    "name": "orbbec_live",
    "width": 1280,
    "height": 720,
    "fps": 30,
    "interval": 0.1,
    "targets": ["person"],
    "recognize_faces": true,
    "auto_register_dynamic": true,
    "dynamic_prefix": "person",
    "max_saved_images": 100,
    "replace_existing": true
  }')

runId=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<< "$runResponse")
echo "$runResponse" | python3 -m json.tool
echo "runId=$runId"
```

### 普通 USB/OpenCV 相机启动命令

```bash
runResponse=$(curl -s -X POST "http://127.0.0.1:8000/camera/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "camera_source": "opencv",
    "camera_index": 0,
    "name": "opencv_live",
    "width": 1280,
    "height": 720,
    "interval": 0.1,
    "targets": ["person"],
    "recognize_faces": true,
    "auto_register_dynamic": true,
    "max_saved_images": 100,
    "replace_existing": true
  }')

runId=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<< "$runResponse")
echo "$runResponse" | python3 -m json.tool
echo "runId=$runId"
```

如果你想改成只保留最新 30 帧图片，把 `max_saved_images` 改成：

```json
"max_saved_images": 30
```

启动成功后会返回：

```json
{
  "run_id": "9f57ef3e-e105-4d8b-8b7c-8e9f2f6d2c48",
  "status": "starting",
  "run_name": "orbbec_live",
  "input_dir": "images/orbbec_live",
  "output_dir": "images/output/orbbec_live",
  "max_saved_images": 100,
  "frame_count": 0,
  "latest_sample": null
}
```

如果看到 `runId=9f57...` 这种输出，说明变量已经保存好了。后面查询、取图、停止都可以直接用 `$runId`，不用手动替换真实 ID。

## 5. 查看运行状态

如果你是按第 4 节启动的，直接运行：

```bash
curl "http://127.0.0.1:8000/camera/runs/$runId"
```

你会看到类似：

```json
{
  "run_id": "9f57ef3e-e105-4d8b-8b7c-8e9f2f6d2c48",
  "status": "running",
  "run_name": "orbbec_live",
  "max_saved_images": 100,
  "frame_count": 128,
  "error": null,
  "latest_sample": {
    "index": 128,
    "elapsed_seconds": 12.7,
    "input_path": "images/orbbec_live/orbbec_live-000128.jpg",
    "output_path": "images/output/orbbec_live/orbbec_live-000128.jpg",
    "results": [
      {
        "found": true,
        "target": "person",
        "detection": {
          "label": "person",
          "confidence": 0.87,
          "box": [120, 80, 420, 720]
        }
      }
    ],
    "face_recognition": {
      "recognized_count": 1,
      "matches": [
        {
          "identity": "person01",
          "library": "dynamic",
          "similarity": 1.0,
          "box": [180, 90, 260, 210]
        }
      ]
    }
  }
}
```

重点字段：

- `status`：`running` 表示正在运行。
- `frame_count`：已经处理的帧数。
- `max_saved_images`：当前 run 最多保留多少帧图片。
- `latest_sample.input_path`：最新原始图片路径。
- `latest_sample.output_path`：最新标注图片路径。
- `latest_sample.results`：YOLO 物体检测结果。
- `latest_sample.face_recognition`：人脸识别结果。

## 6. 物品名字和框坐标在哪里看

### 情况 A：启动时传了 `targets`

上面的启动命令传了：

```json
"targets": ["person"]
```

这种模式返回的是“目标对准结果”。物品名字和框坐标在：

```text
latest_sample.results[0].detection
```

示例：

```json
{
  "label": "person",
  "confidence": 0.87,
  "box": [120, 80, 420, 720]
}
```

字段解释：

- `label`：物品名字，例如 `person`
- `confidence`：置信度，越接近 1 越可靠
- `box`：框坐标，格式是 `[x1, y1, x2, y2]`
- `x1, y1`：左上角坐标
- `x2, y2`：右下角坐标

如果没有识别到目标，`detection` 会是 `null`，可以看：

```text
latest_sample.results[0].found
latest_sample.results[0].miss_reason
```

### 情况 B：启动时不传 `targets`

如果你想看 YOLO 识别到的所有物体，不要传 `targets`：

```bash
runResponse=$(curl -s -X POST "http://127.0.0.1:8000/camera/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "camera_source": "orbbec",
    "camera_index": 0,
    "name": "orbbec_all",
    "width": 1280,
    "height": 720,
    "interval": 0.1,
    "recognize_faces": true,
    "auto_register_dynamic": true,
    "max_saved_images": 100,
    "replace_existing": true
  }')

runId=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<< "$runResponse")
echo "$runResponse" | python3 -m json.tool
echo "runId=$runId"
```

这种模式下，每个物体都在：

```text
latest_sample.results
```

每条记录类似：

```json
{
  "label": "chair",
  "confidence": 0.62,
  "box": [700, 330, 900, 710]
}
```

## 7. 查看最近多帧结果

查看最近 50 帧：

```bash
curl "http://127.0.0.1:8000/camera/runs/$runId/frames?limit=50"
```

返回里的每一帧都有：

```text
frames[].results
frames[].face_recognition
frames[].input_path
frames[].output_path
```

注意：接口内存里可以保留最近的结果记录，但磁盘图片默认只保留最新 100 帧。超过 100 的旧图片路径可能已经被自动删除。

## 8. 人脸识别结果在哪里看

人脸识别结果在：

```text
latest_sample.face_recognition.matches
```

示例：

```json
{
  "identity": "person01",
  "library": "dynamic",
  "similarity": 1.0,
  "box": [180, 90, 260, 210]
}
```

字段解释：

- `identity`：人脸身份名，例如 `person01`、`zhangzhan`
- `library`：来自哪一个人脸库
- `dynamic`：动态库，运行中首次检测到后自动注册，服务重启清空
- `fixed`：固定库，开发者手动注册，保存到 `data/face_registry.json`
- `similarity`：相似度
- `box`：人脸框坐标，格式也是 `[x1, y1, x2, y2]`

## 9. 查看最新标注图片

标注图片保存到：

```text
images/output/<run_name>/
```

例如：

```text
images/output/orbbec_live/orbbec_live-000128.jpg
```

因为默认只保留最新 100 帧，所以目录里不会无限增长。

也可以通过接口下载最新一张标注图：

```bash
curl "http://127.0.0.1:8000/camera/runs/$runId/latest-image" --output latest.jpg
```

下载后查看：

```bash
xdg-open latest.jpg
```

如果 Ubuntu 没有桌面环境，可以把 `latest.jpg` 复制到有桌面的电脑上查看。

## 10. 停止持续检测

停止后台任务并释放相机：

```bash
curl -X DELETE "http://127.0.0.1:8000/camera/runs/$runId"
```

停止后再次查询：

```bash
curl "http://127.0.0.1:8000/camera/runs/$runId"
```

如果看到：

```json
{
  "status": "stopped"
}
```

说明已经停止。

## 11. 固定人脸库怎么注册

固定人脸库只由开发者手动注册，保存到：

```text
data/face_registry.json
```

### 第一步：找候选人脸

使用一张清楚的人脸图片：

```bash
curl -X POST "http://127.0.0.1:8000/faces/candidates" \
  -F "file=@images/orbbec_live/orbbec_live-000001.jpg" \
  -F "annotate=true"
```

返回里会有 `faces[].face_id`：

```json
{
  "faces": [
    {
      "face_id": "5f524e21-cf79-48ed-9ccb-f5072b0d7d3f",
      "box": [180, 90, 260, 210]
    }
  ]
}
```

### 第二步：注册固定身份

把 `face_id` 绑定成固定身份，例如 `zhangzhan`：

```bash
curl -X POST "http://127.0.0.1:8000/faces/register" \
  -H "Content-Type: application/json" \
  -d '{
    "identity": "zhangzhan",
    "face_id": "5f524e21-cf79-48ed-9ccb-f5072b0d7d3f"
  }'
```

### 第三步：查看固定库

```bash
curl "http://127.0.0.1:8000/faces/identities"
```

返回里：

```json
{
  "fixed": [
    {
      "identity": "zhangzhan"
    }
  ],
  "dynamic": []
}
```

后续持续检测时，如果识别到这个人，`library` 会显示为 `fixed`。

## 12. 常见问题

### 1. 启动 run 返回 409

默认启动新任务会自动停掉同一个相机上的旧任务，一般不会返回 409。

如果你把 `replace_existing` 设置成 `false`，并且同一个相机已经有任务在跑，才会返回 409。此时先停止旧任务：

```bash
curl -X DELETE "http://127.0.0.1:8000/camera/runs/$runId"
```

如果忘了 `run_id`，最简单的方法是重启 API 服务。

### 2. status 是 error

查询状态：

```bash
curl "http://127.0.0.1:8000/camera/runs/$runId"
```

看返回里的：

```text
error
```

常见原因：

- 相机被其他程序占用
- Orbbec SDK 没装好
- 模型文件路径不对
- 没有权限访问相机

### 3. 没有人脸名字

看：

```text
latest_sample.face_recognition.miss_reason
```

常见值：

- `no_faces`：画面里没检测到脸，可能脸太小、太糊、侧脸太多
- `no_identity_match`：检测到脸，但没匹配到固定库或动态库
- `no_registered_identities`：没有可用人脸库，且没有开启动态注册

如果要自动给陌生人注册成 `person01`、`person02`，启动 run 时要带：

```json
"auto_register_dynamic": true
```

### 4. 只想看物品检测，不做人脸识别

启动 run 时设置：

```json
"recognize_faces": false
```

这时 `face_recognition` 会是 `null`。

### 5. 输出图片会不会越来越多

现在默认不会无限增长。每个持续 run 默认只保留最新：

```json
"max_saved_images": 100
```

超过 100 后，旧的原始图片和标注图片会自动删除。

如果测试结束后还想手动清理输出目录：

```bash
rm -rf images/orbbec_live images/output/orbbec_live
```

只删除测试输出，不要删除 `models/` 和 `data/face_registry.json`。
