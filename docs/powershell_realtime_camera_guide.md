# PowerShell 持续实时相机检测使用方法

这份文档给新手使用：在 Windows PowerShell 里启动持续实时相机检测，让后端一直读取相机画面，执行 YOLO 物体检测和人脸识别，并持续输出标注图片。

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

## 2. 启动持续实时检测

### 方式 A：检测所有 YOLO 能识别的物体

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

### 方式 B：只检测 person

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
latest_sample.results[0].detection
```

查看最新目标：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status.latest_sample.results[0].detection
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
$detection = $status.latest_sample.results[0].detection
$detection.label
$detection.box
```

如果没有识别到目标，`detection` 会是空值，可以看：

```powershell
$status.latest_sample.results[0].found
$status.latest_sample.results[0].miss_reason
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
$sourceImage = "images\orbbec_live\orbbec_live-000001.jpg"
```

### 第二步：检测这张图里有哪些人脸

```powershell
$form = @{
  file = Get-Item $sourceImage
  annotate = "true"
}

$candidates = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/faces/candidates" `
  -Method Post `
  -Form $form

$candidates
```

返回里重点看：

```text
faces[].face_id
faces[].box
output_path
```

示例：

```json
{
  "face_count": 1,
  "faces": [
    {
      "face_id": "5f524e21-cf79-48ed-9ccb-f5072b0d7d3f",
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
$faceId = $candidates.faces[0].face_id
$faceId
```

如果图片里有多个人脸，需要根据 `output_path` 里的框，选择对应的 `face_id`。

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

PowerShell 的引号规则容易把 JSON 传坏。建议用本文里的 `Invoke-RestMethod`，不要直接手写一长串 `curl.exe --data-raw "{...}"`。

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
- 传了 `targets = @("person")`：坐标在 `$status.latest_sample.results[0].detection`

### 标注图片没有变化

重新查状态：

```powershell
$status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/camera/runs/$runId"
$status.status
$status.error
$status.frame_count
```

如果 `status` 是 `error`，看 `$status.error` 的错误内容。
