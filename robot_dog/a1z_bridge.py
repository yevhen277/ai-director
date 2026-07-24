#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DirectorX ↔ GALAXEA A1Z 官方控制协议桥（HTTP → Unix socket 透传）

官方 a1z server（GALAXEA-A1Z SDK gripper 分支 a1z/robots/server.py）监听
Unix socket /tmp/a1z.sock，协议为换行结尾的 JSON：
    请求:  {"cmd": "<name>", "args": {...}}
    响应:  {"ok": true, "data": {...}}  或  {"ok": false, "error": "<message>"}
    指令集: status | move | gripper | dance | stop | info | estop | release

浏览器无法直连 Unix socket，本桥将其逐字透传为本地 HTTP：
    POST http://127.0.0.1:8766/a1z   Body: {"cmd":"move","args":{"joints":[0,60,-60,0,0,0],"speed":0.5}}
    GET  http://127.0.0.1:8766/health  健康检查

使用步骤（在连接机械臂的 Linux 主机上）：
    1. 启动官方服务:  python tools/a1zctl serve --with-gripper
    2. 启动本桥:      python a1z_bridge.py            # 默认 127.0.0.1:8766
                      python a1z_bridge.py --host 0.0.0.0 --port 8766  # 允许局域网访问
    3. DirectorX 控制条切换到 A1Z·HTTP

仅依赖 Python 标准库。move/dance 为阻塞指令，超时放宽到 75s（与浏览器端超时配合）。
"""
import argparse
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_CMDS = {"status", "move", "gripper", "dance", "stop", "info", "estop", "release"}


def rpc(sock_path: str, req: dict, timeout: float) -> dict:
    """向官方 server 发送一条 JSON 行请求并读取响应。"""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    line = buf.split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    sock_path = "/tmp/a1z.sock"

    # -- CORS --
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "service": "a1z_bridge", "sock": self.sock_path})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path != "/a1z":
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            cmd = req.get("cmd", "")
            if cmd not in ALLOWED_CMDS:
                raise ValueError(f"unsupported cmd '{cmd}' (allowed: {sorted(ALLOWED_CMDS)})")
            timeout = 75.0 if cmd in {"move", "dance"} else 8.0
            resp = rpc(self.sock_path, {"cmd": cmd, "args": req.get("args", {})}, timeout)
        except FileNotFoundError:
            resp = {"ok": False, "error": f"bridge: official server socket not found ({self.sock_path}) — start `python tools/a1zctl serve --with-gripper` first"}
        except ConnectionRefusedError:
            resp = {"ok": False, "error": "bridge: official server refused connection — is `a1zctl serve` running?"}
        except socket.timeout:
            resp = {"ok": False, "error": "bridge: official server response timeout"}
        except Exception as e:
            resp = {"ok": False, "error": f"bridge: {e}"}
        self._json(200, resp)

    def log_message(self, *args):  # 静音访问日志
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="DirectorX A1Z protocol bridge")
    ap.add_argument("--sock", default="/tmp/a1z.sock", help="官方 server 的 Unix socket 路径")
    ap.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址（局域网访问用 0.0.0.0）")
    ap.add_argument("--port", type=int, default=8766, help="HTTP 监听端口")
    args = ap.parse_args()
    Handler.sock_path = args.sock
    print(f"[a1z_bridge] listening on http://{args.host}:{args.port}  →  {args.sock}")
    print("[a1z_bridge] 请先确认官方服务已启动: python tools/a1zctl serve --with-gripper")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
