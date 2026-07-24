[中文](#中文版) | [English](#open-a1z-teleop)

# Open A1Z Teleop

Servo leader arm -> A1Z follower arm teleoperation over SocketCAN.

## Table of Contents

- [Open A1Z Teleop](#open-a1z-teleop)
  - [Hardware Installation Guide](#hardware-installation-guide)
  - [Installation](#installation)
  - [Usage](#usage)
  - [Startup Sequence](#startup-sequence)
  - [Configuration](#configuration)
  - [Key Parameters](#key-parameters)
  - [Servo Setup Tools](#servo-setup-tools)
  - [Project Structure](#project-structure)
  - [Acknowledgements](#acknowledgements)
  - [Disclaimer](#disclaimer)

## Hardware Installation Guide

Detailed assembly instructions for the servo leader arm:

- [English](hardware/A1Z-T_Installation_Guide_EN.md)
- [中文](hardware/A1Z-T_Installation_Guide_CN.md)

## Installation

```bash
# 1. Clone this repo (with submodules)
git clone --recurse-submodules https://github.com/userguide-galaxea/OpenA1Z-T.git
cd open-a1z-t

# 2. Create environment
conda create -n teleop python=3.11
conda activate teleop

# 3. Install packages
pip install -e GALAXEA-A1Z/
pip install -e .

# 4. Setup CAN (each boot)
bash scripts/setup_can.sh can0
# For dual arm, also setup can1:
bash scripts/setup_can.sh can1
```

> **Note:** GALAXEA-A1Z is included as a git submodule tracking the `gripper` branch.
> If you already cloned without `--recurse-submodules`, run:
> `git submodule update --init --recursive`

## Usage

```bash
# Single arm (default)
python teleop.py --port /dev/ttyACM0

# Dual arm (separate USB ports)
python teleop.py --dual --port /dev/ttyACM0 --port_right /dev/ttyACM1 --can can0 --can_right can1

# Dual arm (daisy-chained on same USB, IDs 1-14)
python teleop.py --dual --port /dev/ttyACM0 --can can0 --can_right can1

# Without gripper
python teleop.py --port /dev/ttyACM0 --no_gripper
```

## Startup Sequence

1. Follower arm drives to zero position
2. Leader arm locks at zero (position mode)
3. **Press Enter** to start teleoperation
4. Leader arm releases (free to move)
5. Follower tracks leader movements

Stop: `Ctrl+C`.

## Configuration

Edit `config/teleop.yaml` to adjust:

- Gripper calibration ticks
- Joint direction signs
- Follower PD gains
- Force feedback parameters

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--port` | /dev/ttyACM0 | Leader serial port |
| `--port_right` | (same as --port) | Right leader port in dual mode |
| `--can` | can0 | Follower SocketCAN channel |
| `--can_right` | can1 | Right follower CAN in dual mode |
| `--dual` | off | Enable dual arm mode |
| `--no_gripper` | off | Disable gripper |

## Servo Setup Tools

One-time motor configuration before first use:

```bash
# 1. Scan all baudrates and list detected motors
python3 tools/scan_servos.py --port /dev/ttyACM0

# 2. Flash motor IDs (left arm: IDs 1-7)
#    Connect motors ONE AT A TIME and follow the prompts
python3 tools/setup_servo_ids.py --port /dev/ttyACM0

# 3. Configure right arm for dual-arm operation
#    Changes factory ID 1-7 @ 57600 baud -> ID 8-14 @ 1 Mbaud
#    Connect ONLY the right arm before running
python3 tools/setup_right_servo_ids.py --port /dev/ttyACM0

# If interrupted after IDs changed but baud not yet updated:
python3 tools/setup_right_servo_ids.py --fix-baud --port /dev/ttyACM0
```

After setup, both arms can share one USB port (left IDs 1-7, right IDs 8-14, both @ 1 Mbaud).

## Project Structure

```
open-a1z-t/
├── teleop.py           # Main teleop script
├── leader/             # Servo leader driver package
│   └── servo_bus.py   # DynamixelBus + DynamixelServoReader
├── config/
│   └── teleop.yaml     # Configuration
├── scripts/
│   └── setup_can.sh    # CAN interface setup
├── tools/
│   ├── scan_servos.py      # Scan port for Dynamixel motors
│   ├── setup_servo_ids.py  # Flash motor IDs 1-7 (left arm)
│   └── setup_right_servo_ids.py  # Configure right arm: ID 1-7 -> ID 8-14 @ 1 Mbaud
└── GALAXEA-A1Z/        # A1Z SDK (submodule, gripper branch)
```

## Acknowledgements

Servo leader driver is based on [trlc-dk1](https://github.com/robot-learning-co/trlc-dk1) by Robot Learning Co. Thanks for the open-source contribution.

## Disclaimer

Dynamixel is a registered trademark of ROBOTIS Co., Ltd. This document references Dynamixel products solely to describe the components required for assembly, and does not imply any association with or endorsement by ROBOTIS Co., Ltd.

DaMiao is a trademark of Shenzhen Damiao Technology Co., Ltd. This project is not endorsed by or affiliated with Shenzhen Damiao Technology Co., Ltd.

---

[English](#open-a1z-teleop) | [中文](#中文版)

# 中文版

## 目录

- [硬件安装指南](#硬件安装指南)
- [安装](#安装)
- [使用方法](#使用方法)
- [启动流程](#启动流程)
- [配置](#配置)
- [关键参数](#关键参数)
- [舵机配置工具](#舵机配置工具)
- [项目结构](#项目结构)
- [致谢](#致谢)
- [免责声明](#免责声明)

## Open A1Z Teleop

通过 SocketCAN 实现servo leader手臂到 A1Z leader手臂的遥操作。

## 硬件安装指南

servo leader手臂的详细装配说明：

- [English](hardware/A1Z-T_Installation_Guide_EN.md)
- [中文](hardware/A1Z-T_Installation_Guide_CN.md)

## 安装

```bash
# 1. 克隆本仓库（含子模块）
git clone --recurse-submodules https://github.com/userguide-galaxea/OpenA1Z-T.git
cd open-a1z-t

# 2. 创建环境
conda create -n teleop python=3.11
conda activate teleop

# 3. 安装依赖
pip install -e GALAXEA-A1Z/
pip install -e .

# 4. 配置 CAN 接口（每次开机需要）
bash scripts/setup_can.sh can0
# 双臂模式还需配置 can1：
bash scripts/setup_can.sh can1
```

> **注意：** GALAXEA-A1Z 以 git submodule 形式引入，追踪 `gripper` 分支。
> 如果 clone 时忘记加 `--recurse-submodules`，可补执行：
> `git submodule update --init --recursive`

## 使用方法

```bash
# 单臂模式（默认）
python teleop.py --port /dev/ttyACM0

# 双臂模式（独立 USB 端口）
python teleop.py --dual --port /dev/ttyACM0 --port_right /dev/ttyACM1 --can can0 --can_right can1

# 双臂模式（同一 USB 菊花链，ID 1-14）
python teleop.py --dual --port /dev/ttyACM0 --can can0 --can_right can1

# 不使用夹爪
python teleop.py --port /dev/ttyACM0 --no_gripper
```

## 启动流程

1. leader手臂回零
2. leader手臂锁定在零位（位置模式）
3. **按回车键**开始遥操作
4. leader手臂释放（可自由移动）
5. leader手臂跟踪leader运动

停止：`Ctrl+C`。

## 配置

编辑 `config/teleop.yaml` 可调整：

- 夹爪校准刻度值
- 关节方向符号
- leader PD 增益
- 力反馈参数

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | /dev/ttyACM0 | leader串口号 |
| `--port_right` | （同 --port） | 双臂模式下右臂串口号 |
| `--can` | can0 | leader SocketCAN 通道 |
| `--can_right` | can1 | 双臂模式下右臂 CAN 通道 |
| `--dual` | 关 | 启用双臂模式 |
| `--no_gripper` | 关 | 禁用夹爪 |

## 舵机配置工具

首次使用前需要配置电机：

```bash
# 1. 扫描所有波特率并列出检测到的电机
python3 tools/scan_servos.py --port /dev/ttyACM0

# 2. 刷写电机 ID（左臂：ID 1-7）
#    每次只连接一个电机，按提示操作
python3 tools/setup_servo_ids.py --port /dev/ttyACM0

# 3. 配置右臂用于双臂操作
#    将出厂 ID 1-7 @ 57600 波特率改为 ID 8-14 @ 1 Mbaud
#    运行前仅连接右臂
python3 tools/setup_right_servo_ids.py --port /dev/ttyACM0

# 如果 ID 已改但波特率未更新（如中断后）：
python3 tools/setup_right_servo_ids.py --fix-baud --port /dev/ttyACM0
```

配置完成后，双臂可共享一个 USB 端口（左臂 ID 1-7，右臂 ID 8-14，均 @ 1 Mbaud）。

## 项目结构

```
open-a1z-t/
├── teleop.py           # 主遥操作脚本
├── leader/             # Leader arm driver package
│   └── servo_bus.py   # DynamixelBus + DynamixelServoReader
├── config/
│   └── teleop.yaml     # 配置文件
├── scripts/
│   └── setup_can.sh    # CAN 接口设置脚本
├── tools/
│   ├── scan_servos.py      # 扫描串口检测 Dynamixel 电机
│   ├── setup_servo_ids.py  # 刷写左臂电机 ID 1-7
│   └── setup_right_servo_ids.py  # 配置右臂：ID 1-7 → ID 8-14 @ 1 Mbaud
└── GALAXEA-A1Z/        # A1Z SDK（子模块，gripper 分支）
```

## 致谢

Leader arm driver 基于 [trlc-dk1](https://github.com/robot-learning-co/trlc-dk1)（Robot Learning Co.），感谢开源贡献。

## 免责声明

Dynamixel 是 ROBOTIS 公司的注册商标。本文档仅为描述装配所需组件而引用 Dynamixel 产品，不表示与 ROBOTIS 公司存在任何关联或获得其授权。

DaMiao 是深圳市达妙科技有限公司的商标。本项目与深圳市达妙科技有限公司不存在任何关联或授权关系。
