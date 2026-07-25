# Director Vision Tool / DirectorX

面向机械臂摄影系统的视觉与导演后端。项目使用 FastAPI 提供 HTTP/WebSocket 接口，负责从图片或摄像头画面中检测目标、识别人脸身份、输出机械臂可用的结构化坐标，并为 DirectorX 页面和机械臂/TCP 控制链路提供实时视觉数据。

当前仓库适合做三类事情：本地验证 YOLO/人脸识别效果、给前端/DirectorX 页面提供视觉 API、在 Ubuntu 设备上部署为机械臂摄影系统的视觉服务。

## 一句话介绍
DirectorX 是一个理解导演语言并驱动机器人完成真实拍摄的具身智能摄影系统，面向影视创作者、短视频创作者以及普通内容创作者，让“一句创意”能够转化为现实中的电影镜头。

## 为什么选择做这个主题
我们团队由广播电视编导、软件工程、机器人等不同背景成员组成。作为编导专业学生，我们长期面对一个核心问题：脑海中的画面往往比实际拍摄能力更丰富，但从创意到成片之间存在巨大的执行门槛。一个镜头的实现需要摄影知识、设备操作、灯光调度以及多人协作，即使拥有好的创意，也可能因为缺少专业团队和设备而无法实现。随着AI内容生成技术的发展，文字生成图片、视频已经降低了内容生产门槛，但现实世界中的拍摄执行仍然依赖人工。因此，我们希望探索一种新的创作方式，让导演只需要表达想法，机器人作为智能摄影搭档完成后续执行，让创意真正成为现实。

## 机器人具体在做什么
DirectorX 希望让机器人从“执行固定轨迹的设备”升级为“理解创作意图的摄影伙伴”。用户输入一句导演语言，例如“拍摄一个人在窗边安静思考的画面”，系统会理解其中包含的主体、场景、构图和镜头语言，并生成对应的摄影方案，再通过机器人完成实际拍摄动作。目前作品实现了目标识别、摄影控制以及机械臂运动执行等核心能力，可以根据指定目标完成追踪、构图调整和镜头运动，实现从自然语言输入到真实拍摄结果的闭环。

## 核心能力

- **YOLO 物体检测**：检测图片、USB 摄像头或 Orbbec 摄像头画面中的目标，返回类别、置信度和边框坐标。
- **机械臂坐标接口**：提供 `/robot/detect/image` 和 `/robot/detect/camera`，返回 `object_name`、左上角和右下角坐标，便于机械臂控制层直接读取。
- **目标居中/运镜辅助**：提供 `/aim/image` 和 `/aim/camera`，根据目标中心与画面中心偏移返回 `pan_left`、`pan_right`、`tilt_up`、`tilt_down`、`hold` 或 `search`。
- **现场指认式人脸识别**：基于 InsightFace `buffalo_l`，支持候选脸检测、身份注册、单身份识别和全身份识别。
- **连续摄像头 run**：后台持续读取摄像头、保存最近帧、生成标注图，并通过 HTTP、MJPEG 和 WebSocket 输出实时结果。
- **DirectorX 页面与导演规划**：内置 `/directorx` 页面，支持视觉调试、目标选择、导演规划请求和机械臂状态联动。
- **TCP 目标发送与关节反馈**：可向外部机械臂控制服务发送视觉目标，并接收/广播机械臂关节状态。
- **Ubuntu 部署**：提供安装脚本和 systemd 服务配置，便于部署为常驻后端服务。

## 环境准备

建议使用 Python 3.10 或更新版本。首次运行前创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

确认 `models/` 目录下存在 `.env` 中配置的 YOLO 模型，例如：

```text
models/yolov8n.pt
models/yolo26s.pt
```

如果模型路径不同，请修改 `.env` 中的 `YOLO_MODEL`。

## 快速启动

在 Windows PowerShell 中启动 FastAPI：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
curl http://127.0.0.1:8000/health
```

打开 DirectorX 页面：

```text
http://127.0.0.1:8000/directorx
```

API 默认本地地址为：

```text
http://127.0.0.1:8000
```

## 常用接口示例

### 图片物体检测

```powershell
curl -X POST http://127.0.0.1:8000/detect/image -F "file=@images/0001.jpg"
```

返回所有 YOLO 检测结果，格式包含 `label`、`confidence` 和 `box`。

### 机械臂图片检测

```powershell
curl -X POST http://127.0.0.1:8000/robot/detect/image -F "target=person" -F "file=@images/0001.jpg"
```

返回适合机械臂读取的结构：

```json
{
  "object_count": 1,
  "objects": [
    {
      "object_name": "person",
      "confidence": 0.94,
      "top_left": {"x": 120, "y": 80},
      "bottom_right": {"x": 420, "y": 720}
    }
  ]
}
```

### 目标对准

```powershell
curl -X POST http://127.0.0.1:8000/aim/image -F "target=person" -F "tolerance_ratio=0.08" -F "file=@images/0001.jpg"
```

关注返回中的 `found`、`command`、`centered`、`offset_ratio` 和 `detection.box`。

### 人脸候选与注册

先检测可选人脸：

```powershell
curl -X POST http://127.0.0.1:8000/faces/candidates -F "annotate=true" -F "file=@images/0001.jpg"
```

再把返回的 `face_id` 绑定为业务身份：

```powershell
curl -X POST http://127.0.0.1:8000/faces/register -H "Content-Type: application/json" -d '{"identity":"male_lead","face_id":"FACE_ID","threshold":0.45}'
```

### 识别全部已注册身份

```powershell
curl -X POST http://127.0.0.1:8000/faces/recognize/all -F "annotate=true" -F "file=@images/0002.jpg"
```

### 启动连续摄像头 run

```powershell
curl -X POST http://127.0.0.1:8000/camera/runs -H "Content-Type: application/json" -d '{"camera_source":"opencv","camera_index":0,"name":"live","width":1280,"height":720,"fps":30,"interval":0.1,"targets":["person"],"recognize_faces":true,"auto_register_dynamic":true}'
```

常用 run 接口：

```text
GET    /camera/runs/{run_id}
GET    /camera/runs/{run_id}/frames?limit=50
GET    /camera/runs/{run_id}/latest-image
GET    /camera/runs/{run_id}/preview.mjpg
WS     /camera/runs/{run_id}/boxes.ws
POST   /camera/runs/{run_id}/tcp-target
DELETE /camera/runs/{run_id}
```

完整接口说明见 [docs/api.md](docs/api.md)。

## CLI 使用

### 图片检测

```powershell
.\.venv\Scripts\python.exe .\vision_cli.py .\images\0001.jpg
```

只输出 JSON，不保存标注图：

```powershell
.\.venv\Scripts\python.exe .\vision_cli.py .\images\0001.jpg --no-output
```

按目标检测并输出对准结果：

```powershell
.\.venv\Scripts\python.exe .\vision_cli.py .\images\0001.jpg --target person --tolerance 0.08
```

查看当前模型类别：

```powershell
.\.venv\Scripts\python.exe .\vision_cli.py dummy.jpg --classes
```

### 摄像头检测

使用 OpenCV 摄像头采样一次：

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source opencv --camera-index 0 --target person --name test001
```

连续采样 10 秒，每 0.5 秒检测一次：

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source opencv --camera-index 0 --duration 10 --interval 0.5 --target person --name live_test
```

列出 Orbbec 设备：

```powershell
.\.venv\Scripts\python.exe .\camera_cli.py --source orbbec --list-orbbec
```

## 配置说明

配置从项目根目录 `.env` 读取，模板见 `.env.example`。

| 配置 | 说明 |
| --- | --- |
| `YOLO_MODEL` | YOLO 模型路径，例如 `models/yolov8n.pt`。 |
| `YOLO_CONFIDENCE` | 主检测置信度阈值。 |
| `FACE_MODEL` | InsightFace 模型名，默认 `buffalo_l`。 |
| `FACE_THRESHOLD` | 默认人脸相似度阈值。 |
| `FACE_REGISTRY_PATH` | 固定身份注册文件路径，默认 `data/face_registry.json`。 |
| `DEFAULT_CAMERA_SOURCE` | 默认摄像头来源，`opencv` 或 `orbbec`。 |
| `DEFAULT_CAMERA_INDEX` | 默认摄像头序号。 |
| `CAMERA_RUN_MAX_SAVED_IMAGES` | 连续 run 保留的最近图片数量。 |
| `TCP_FACE_ENABLED` | 是否启用视觉目标 TCP 发送。 |
| `TCP_FACE_HOST` / `TCP_FACE_PORT` | 外部机械臂控制服务地址。 |
| `TCP_FACE_IDENTITY` | 默认跟踪的人脸身份。 |
| `TCP_FACE_SEND_FPS` | TCP 目标发送频率。 |
| `TCP_FACE_TRACK_TTL_SECONDS` | 目标跟踪有效时间。 |
| `ROBOT_JOINT_TCP_DEFAULT_UNIT` | 接收机械臂关节反馈时的默认单位，默认 `deg`。 |
| `DIRECTOR_PLAN_MODE` | 导演规划模式，默认 `llm`。 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | LLM 导演规划接口配置。 |
| `LLM_TEMPERATURE` / `LLM_TIMEOUT_SECONDS` | LLM 请求参数。 |

不要提交本机 `.env` 中的密钥、设备 IP 或私有配置。

## 目录结构

```text
app/        FastAPI 后端、YOLO 检测、人脸识别、摄像头 run、TCP 与导演规划逻辑
data/       人脸身份注册等运行数据
deploy/     Ubuntu 安装脚本和 systemd 服务文件
docs/       API 与实时摄像头使用文档
images/     输入图片、摄像头采样图片和标注输出图片
models/     YOLO 模型文件
robot_dog/  DirectorX 页面和 A1Z bridge 相关文件
tests/      pytest 测试
```

几个关键入口：

```text
app/api.py                 FastAPI 应用入口
app/detector.py            YOLO 检测封装
app/face_recognition.py    人脸识别封装
app/camera_runs.py         连续摄像头 run 管理
app/director_planner.py    DirectorX 导演规划
vision_cli.py              图片检测 CLI
camera_cli.py              摄像头检测 CLI
```

## 测试

运行现有测试：

```powershell
python -m pytest
```

如果本机没有摄像头、Orbbec SDK、模型文件或 InsightFace 运行环境，部分与硬件/模型相关的验证可能需要在目标设备上执行。

## Ubuntu 部署

仓库提供部署脚本：

```bash
bash deploy/install_ubuntu.sh
```

默认部署路径和服务：

```text
/opt/director-vision
/etc/systemd/system/director-vision.service
```

服务启动后默认监听：

```text
http://<Ubuntu机器IP>:8000
```

常用 systemd 命令：

```bash
sudo systemctl status director-vision.service
sudo systemctl restart director-vision.service
sudo journalctl -u director-vision.service -f
```

Ubuntu 上需要确认模型文件已放到部署目录的 `models/` 下，并根据实际设备修改 `/opt/director-vision/.env`。

## 常见问题

### `/health` 能访问，但检测接口很慢

首次调用 YOLO 或 InsightFace 时需要加载模型；InsightFace 首次运行还可能下载 `buffalo_l` 模型。首次请求较慢是正常现象。

### 检测不到目标

检查 `YOLO_MODEL` 是否存在，尝试降低 `YOLO_CONFIDENCE`，或使用 `--classes` 查看当前模型支持的类别。也可以在 `/aim/image` 中查看 `labels_seen` 和 `miss_reason`。

### 人脸注册后识别不到

确认注册和识别使用的是同一个后端实例；`face_id` 是临时 ID，通常需要在候选脸检测后尽快注册。可适当调整 `FACE_THRESHOLD` 或请求中的 `threshold`。

### 局域网访问不到 Ubuntu 服务

确认 uvicorn/systemd 绑定 `0.0.0.0`，并开放端口：

```bash
sudo ufw allow 8000/tcp
```

## 相关文档

- [Frontend API Reference](docs/api.md)
- [Windows PowerShell 实时摄像头指南](docs/powershell_realtime_camera_guide.md)
- [Ubuntu 实时摄像头指南](docs/ubuntu_realtime_camera_guide.md)
- [项目描述文档](描述文档.md)
