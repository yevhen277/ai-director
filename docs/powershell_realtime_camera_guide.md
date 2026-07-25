# PowerShell 持续实时相机检测使用方法

这份文档给新手使用：在 Windows 上通过网页或 PowerShell 启动持续实时相机检测，让后端一直读取相机画面，执行 YOLO 物体检测和人脸识别，并持续输出标注图片。

本文所有 PowerShell 命令都按 Windows PowerShell 5.1 编写。

默认地址：

```text
http://127.0.0.1:8000
```

## 1. 启动后端服务

先进入项目目录：

```powershell
cd D:\MyDocument\Download\director111
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

启动 API 服务：

```powershell
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

这个窗口不要关。后面再打开一个新的 PowerShell 窗口执行接口命令。

检查服务是否正常：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

查看当前 PowerShell 版本：

```powershell
$PSVersionTable.PSVersion
```

如果 `Major` 是 `7` 或更高，可以使用本文里的 `Invoke-RestMethod -Form` 上传文件写法。
如果 `Major` 是 `5`，也就是 Windows PowerShell 5.1，上传文件时要用本文后面给出的 `curl.exe -F` 写法，因为 5.1 版的 `Invoke-RestMethod` 没有 `-Form` 参数。

如果要让网页默认使用本机摄像头，确认 `.env` 里有：

```text
DEFAULT_CAMERA_SOURCE=opencv
DEFAULT_CAMERA_INDEX=0
```

修改 `.env` 后要重启 API 服务才会生效。`opencv` 表示本机/USB 摄像头，`0` 通常是默认摄像头索引。

## 2. 启动持续实时检测

### 方式 A：网页按钮启动（推荐）

服务启动后，在浏览器打开：

```text
http://127.0.0.1:8000/
```

网页打开后不会立刻占用相机。点击页面右上角的“启动”按钮后，网页才会开始相机识别。网页会使用 `.env` 里的 `DEFAULT_CAMERA_SOURCE` 和 `DEFAULT_CAMERA_INDEX`，并启用：

```text
YOLO 物品检测
人脸识别
动态人脸自动注册 person01、person02
只保留最新 100 帧图片
```

网页会显示：

- 最新标注输出图片
- 最新一帧识别到的物品名字、置信度和坐标 `[x1, y1, x2, y2]`
- 最新一帧识别到的人脸身份、库类型、相似度和坐标 `[x1, y1, x2, y2]`

点击“停止”按钮会停止后台任务并释放相机。

如果 8000 端口被占用，你用其他端口启动服务，例如：

```powershell
uvicorn app.api:app --host 127.0.0.1 --port 8001
```

那浏览器就打开：

```text
http://127.0.0.1:8001/
```

### 方式 B：PowerShell 检测所有 YOLO 能识别的物体

如果你想看到所有识别到的物体名字和坐标，不要传 `targets`。

```powershell
$body = @{
  camera_source = "orbbec"
  camera_index = 0
  name = "orbbec_live"
  width = 1280
  height = 720
  interval = 0.1
  recognize_faces = $true
  auto_register_dynamic = $true
  max_saved_images = 100
  replace_existing = $true
} | ConvertTo-Json -Compress

$run = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/camera/runs" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body

$global:runId = $run.run_id
$run
```

### 方式 C：PowerShell 只检测 person

如果你只关心人，可以传 `targets = @("person")`。

```powershell
$body = @{
  camera_source = "orbbec"
  camera_index = 0
  name = "orbbec_live"
  width = 1280
  height = 720
  interval = 0.1
  targets = @("person")
  recognize_faces = $true
  auto_register_dynamic = $true
  max_saved_images = 100
  replace_existing = $true
} | ConvertTo-Json -Compress

$run = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/camera/runs" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body

$global:runId = $run.run_id
$run
```

启动成功后会返回 `run_id`，上面的命令已经自动保存到当前 PowerShell 会话的 `$runId` 变量里。后面查状态、取图、停止，都可以直接用 `$runId`。

查看当前保存的 run id：

```powershell
$runId
```

再次启动新的持续检测时，接口默认会先停掉同一个相机上的旧任务，再启动新任务。这个行为由 `replace_existing = $true` 控制。

## 3. 查看实时状态

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status
```

重点看这些字段：

- `status`：`running` 表示正在运行。
- `frame_count`：已经处理了多少帧。
- `latest_sample.input_path`：最新原始图片路径。
- `latest_sample.output_path`：最新标注图片路径。
- `latest_sample.results`：YOLO 物体检测结果。
- `latest_sample.face_recognition`：人脸识别结果。

## 4. 图片输出在哪里

持续检测会一直写图片：

```text
原始图片：images\orbbec_live\orbbec_live-000001.jpg
标注图片：images\output\orbbec_live\orbbec_live-000001.jpg
```

最新标注图片路径可以这样看：

```powershell
$status.latest_sample.output_path
```

也可以直接从接口下载最新标注图：

```powershell
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/camera/runs/$runId/latest-image" `
  -UseBasicParsing `
  -OutFile ".\latest.jpg"
```

下载后打开当前目录下的：

```text
latest.jpg
```

默认只保留最新 100 帧图片，也就是 `max_saved_images = 100`。超过 100 后，更早的原始图片和标注图片会自动删除，避免硬盘一直增长。

## 5. 物品名字和框坐标在哪里看

### 情况 A：启动时没有传 targets

也就是用了“检测所有 YOLO 能识别的物体”的启动方式。

物体名字和坐标在：

```text
latest_sample.results
```

查看最新一帧所有物体：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status.latest_sample.results
```

每个物体长这样：

```json
{
  "label": "person",
  "confidence": 0.87,
  "box": [120, 80, 420, 720]
}
```

字段意思：

- `label`：物品名字，比如 `person`、`bottle`、`chair`
- `confidence`：置信度
- `box`：框坐标，格式是 `[x1, y1, x2, y2]`

坐标解释：

```text
x1, y1 = 左上角坐标
x2, y2 = 右下角坐标
```

只打印名字和坐标：

```powershell
$status.latest_sample.results | Select-Object label, confidence, box
```

### 情况 B：启动时传了 targets = @("person")

这种模式返回的是“目标对准结果”，物品名字和框坐标在：

```text
@($status.latest_sample.results)[0].detection
```

查看最新目标：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$targetResult = @($status.latest_sample.results)[0]
$targetResult.detection
```

返回类似：

```json
{
  "label": "person",
  "confidence": 0.87,
  "box": [120, 80, 420, 720]
}
```

只取名字和坐标：

```powershell
$targetResult = @($status.latest_sample.results)[0]
$detection = $targetResult.detection
$detection.label
$detection.box
```

如果没有识别到目标，`detection` 会是空值，可以看：

```powershell
$targetResult = @($status.latest_sample.results)[0]
$targetResult.found
$targetResult.miss_reason
```

## 6. 查看最近多帧结果

查看最近 10 帧：

```powershell
$frames = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId/frames?limit=10"
$frames.frames
```

查看最近 10 帧每一帧的标注图路径：

```powershell
$frames.frames | Select-Object index, elapsed_seconds, output_path
```

如果是“检测所有物体”模式，查看最近 10 帧每帧识别到的物体：

```powershell
$frames.frames | ForEach-Object {
  "frame $($_.index)"
  $_.results | Select-Object label, confidence, box
}
```

## 7. 人脸识别结果在哪里看

人脸识别结果在：

```text
latest_sample.face_recognition
```

查看最新一帧识别到的人：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status.latest_sample.face_recognition.matches
```

每个人脸匹配大概长这样：

```json
{
  "identity": "person01",
  "library": "dynamic",
  "similarity": 1.0,
  "box": [310, 130, 430, 270]
}
```

字段意思：

- `identity`：人是谁，比如固定库里的名字，或者动态库自动生成的 `person01`
- `library`：`fixed` 表示固定人脸库，`dynamic` 表示临时动态库
- `similarity`：相似度
- `box`：人脸框坐标，格式也是 `[x1, y1, x2, y2]`

只打印人名和脸框坐标：

```powershell
$status.latest_sample.face_recognition.matches | Select-Object identity, library, similarity, box
```

## 8. 注册固定人脸库

固定人脸库是开发者手动维护的长期人脸库，会保存到：

```text
data\face_registry.json
```

动态库里的 `person01`、`person02` 重启服务后会清空；固定库不会因为重启丢失。

### 第一步：准备一张清楚的人脸图片

可以用持续检测保存下来的原始图。先查最新原始图路径：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$sourceImage = $status.latest_sample.input_path
$sourceImage
```

如果你想手动指定图片，也可以这样：

```powershell
$sourceImage = "images\orbbec_live\orbbec_live-001184.jpg"
```

### 第二步：检测这张图里有哪些人脸

如果你用的是 PowerShell 7 或更高版本，可以这样上传图片：

```powershell
$fullPath = (Resolve-Path $sourceImage).Path

$json = curl.exe -s `
  -X POST `
  --form "file=@$fullPath" `
  --form "annotate=true" `
  "http://127.0.0.1:8000/faces/candidates"

$candidates = $json | ConvertFrom-Json
$candidates
```

如果你用的是 Windows PowerShell 5.1，`Invoke-RestMethod` 不支持 `-Form`，请用这个写法：

```powershell
$fullPath = (Resolve-Path $sourceImage).Path

$json = curl.exe -s `
  -X POST `
  -F "file=@$fullPath" `
  -F "annotate=true" `
  "http://127.0.0.1:8000/faces/candidates"

$candidates = $json | ConvertFrom-Json
$candidates
```

返回里重点看：

```text
faces[].face_id
faces[].box
faces[].confidence
output_path
```

示例：

```json
{
  "face_count": 1,
  "faces": [
    {
      "face_id": "1aefdc74-4df8-445b-add0-5a4fd191de6f",
      "confidence": 0.94,
      "box": [180, 90, 260, 210]
    }
  ],
  "output_path": "images\\output\\orbbec_live-000001_faces.jpg"
}
```

`output_path` 是画了人脸框的图片。打开它确认哪个框是你要注册的人。

### 第三步：保存要注册的 face_id

如果图片里只有一个人脸，可以直接取第一个：

```powershell
$faceId = @($candidates.faces)[0].face_id
$faceId
```

?????@($candidates.faces)[0]` ??????????????????????????????????????????

??????????????????????? `output_path` ???????????????????????`face_id`??????????????????????

```powershell
$candidates.faces | Select-Object face_id, confidence, box
```

如果你想自动选择置信度最高的人脸，可以这样取：

```powershell
$faceId = (@($candidates.faces) | Sort-Object confidence -Descending | Select-Object -First 1).face_id
$faceId
```

如果你已经从列表里确认了某个具体的 `face_id`，手动指定时要加引号：

```powershell
$faceId = "dd2878fc-c4ff-4087-a261-2e01a3dca91b"
```

### 第四步：注册成固定身份

例如注册成 `zhangzhan`：

```powershell
$body = @{
  identity = "zhangzhan"
  face_id = $faceId
  source_image = $sourceImage
} | ConvertTo-Json -Compress

$registered = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/faces/register" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body

$registered
```

注册成功后，这个人会写入固定库 `data\face_registry.json`。

### 第五步：查看固定库

```powershell
$identities = Invoke-RestMethod -Uri "http://127.0.0.1:8000/faces/identities"
$identities.fixed
```

如果看到：

```json
{
  "identity": "zhangzhan"
}
```

说明固定人脸注册成功。

### 第六步：确认持续检测识别到固定身份

持续检测下一次识别到这个人时，人脸结果里会显示：

```json
{
  "identity": "zhangzhan",
  "library": "fixed"
}
```

查看最新识别结果：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status.latest_sample.face_recognition.matches | Select-Object identity, library, similarity, box
```

如果你之前已经把同一个人自动注册成了动态库的 `person01`，建议停止当前 run，然后重新启动一次持续检测。这样固定库身份更容易优先生效。

## 9. 停止持续检测

用 `run_id` 停止：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/camera/runs/$runId" `
  -Method Delete
```

停止后相机会释放，可以再次启动新的持续检测。

## 10. 常见问题

### PowerShell 里 curl 报 JSON 错误

PowerShell 的引号规则容易把 JSON 传坏。发送 JSON 请求时，建议用本文里的 `Invoke-RestMethod -Body $body -ContentType "application/json"`，不要直接手写一长串 `curl.exe --data-raw "{...}"`。

但是上传图片这种 `multipart/form-data` 请求例外：如果你使用 Windows PowerShell 5.1，因为它没有 `Invoke-RestMethod -Form`，可以按本文固定人脸库注册部分的示例使用 `curl.exe -F`。

### 返回 409

默认启动新任务会自动停掉同一个相机上的旧任务，一般不会返回 409。

如果你把 `replace_existing` 设置成 `$false`，并且同一个相机已经有任务在运行，才会返回 409。此时先停掉旧任务：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/camera/runs/$runId" `
  -Method Delete
```

如果忘记了 `run_id`，可以重启 API 服务来释放相机。

### 看不到物体坐标

先确认你用了哪种启动方式：

- 没有传 `targets`：坐标在 `$status.latest_sample.results`
- 传了 `targets = @("person")`：坐标在 `@($status.latest_sample.results)[0].detection`

### 标注图片没有变化

重新查状态：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status.status
$status.error
$status.frame_count
```

如果 `status` 是 `error`，看 `$status.error` 的错误内容。
