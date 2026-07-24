# Ubuntu 持续实时相机检测与人脸识别小白使用指南

这份文档说明如何在 Ubuntu 上使用本项目持续读取相机画面，执行 YOLO 物品检测和人脸识别，并持续输出标注图片。

默认服务地址：

```bash
http://127.0.0.1:8000
```

## 1. 准备项目

把整个项目目录复制到 Ubuntu 机器上，进入项目目录：

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

如果使用 Orbbec 相机，还需要安装 Orbbec Python SDK。当前代码读取 Orbbec 依赖 `pyorbbecsdk`，如果没有安装，接口会提示：

```text
pyorbbecsdk2 is not installed
```

安装好 Orbbec SDK 后，先确认系统能看到相机，并关闭 Orbbec Viewer 或其他占用相机的软件。

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
- 动态人脸库只在内存里，服务重启后自动清空。

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

1. YOLO 物品检测
2. 固定人脸库识别
3. 动态人脸库识别
4. 首次看到陌生人脸时自动注册为 `person01`、`person02`
5. 保存原始图片和标注图片

### Orbbec 相机启动命令

```bash
curl -X POST "http://127.0.0.1:8000/camera/runs" \
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
    "dynamic_prefix": "person"
  }'
```

### 普通 USB/OpenCV 相机启动命令

```bash
curl -X POST "http://127.0.0.1:8000/camera/runs" \
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
    "auto_register_dynamic": true
  }'
```

启动成功后会返回：

```json
{
  "run_id": "9f57ef3e-e105-4d8b-8b7c-8e9f2f6d2c48",
  "status": "starting",
  "run_name": "orbbec_live",
  "input_dir": "images/orbbec_live",
  "output_dir": "images/output/orbbec_live",
  "frame_count": 0,
  "latest_sample": null
}
```

记住返回的 `run_id`，后面查询、取图、停止都要用它。

## 5. 查看运行状态

把下面命令里的 `RUN_ID` 换成真实的 `run_id`：

```bash
curl "http://127.0.0.1:8000/camera/runs/RUN_ID"
```

你会看到类似：

```json
{
  "run_id": "9f57ef3e-e105-4d8b-8b7c-8e9f2f6d2c48",
  "status": "running",
  "run_name": "orbbec_live",
  "frame_count": 128,
  "error": null,
  "latest_sample": {
    "index": 128,
    "elapsed_seconds": 12.7,
    "input_path": "images/orbbec_live/orbbec_live-000128.jpg",
    "output_path": "images/output/orbbec_live/orbbec_live-000128.jpg",
    "results": [
      {
        "label": "person",
        "confidence": 0.87,
        "box": [120, 80, 420, 720]
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

## 6. 物品名字和框坐标在哪里看

YOLO 检测到的物品名字和框坐标在：

```text
latest_sample.results
```

每个物品是一条记录：

```json
{
  "label": "person",
  "confidence": 0.87,
  "box": [120, 80, 420, 720]
}
```

字段解释：

- `label`：物品名字，例如 `person`、`chair`、`bottle`
- `confidence`：置信度，越接近 1 越可靠
- `box`：框坐标，格式是 `[x1, y1, x2, y2]`
- `x1, y1`：左上角坐标
- `x2, y2`：右下角坐标

如果要看最近 50 帧的检测数据：

```bash
curl "http://127.0.0.1:8000/camera/runs/RUN_ID/frames?limit=50"
```

返回里的每一帧都有：

```text
frames[].results
```

这里就是历史帧的物品名字和坐标。

## 7. 人脸识别结果在哪里看

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
- `library`：来自哪个人脸库
- `dynamic`：动态库，运行中首次检测到后自动注册，服务重启清空
- `fixed`：固定库，开发者手动注册，保存到 `data/face_registry.json`
- `similarity`：相似度
- `box`：人脸框坐标，格式也是 `[x1, y1, x2, y2]`

## 8. 查看最新标注图片

标注图片会持续保存到：

```text
images/output/<run_name>/
```

例如：

```text
images/output/orbbec_live/orbbec_live-000128.jpg
```

也可以通过接口下载最新一张标注图：

```bash
curl "http://127.0.0.1:8000/camera/runs/RUN_ID/latest-image" --output latest.jpg
```

下载后查看：

```bash
xdg-open latest.jpg
```

如果 Ubuntu 没有桌面环境，可以把 `latest.jpg` 复制到有桌面的电脑上查看。

## 9. 停止持续检测

停止后台任务并释放相机：

```bash
curl -X DELETE "http://127.0.0.1:8000/camera/runs/RUN_ID"
```

停止后再次查询：

```bash
curl "http://127.0.0.1:8000/camera/runs/RUN_ID"
```

如果看到：

```json
{
  "status": "stopped"
}
```

说明已经停止。

## 10. 固定人脸库怎么注册

固定人脸库只有开发者手动注册才会写入，保存到：

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

## 11. 常见问题

### 1. 启动 run 返回 409

意思是同一个相机已经有任务在跑。先停止旧任务：

```bash
curl -X DELETE "http://127.0.0.1:8000/camera/runs/RUN_ID"
```

如果忘了 `run_id`，最简单的方法是重启 API 服务。

### 2. status 是 error

查询状态：

```bash
curl "http://127.0.0.1:8000/camera/runs/RUN_ID"
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

### 5. 输出图片越来越多

持续检测会不断保存图片：

```text
images/<run_name>/
images/output/<run_name>/
```

测试结束后可以手动清理旧目录：

```bash
rm -rf images/orbbec_live images/output/orbbec_live
```

只删除测试输出，不要删除 `models/` 和 `data/face_registry.json`。

