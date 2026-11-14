"""一次性启动 4 个仿真市场（独立 uvicorn 进程，各自端口）。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
APPS = [
    ("mock_sites.m1_font.app", 8011),
    ("mock_sites.m2_canvas.app", 8012),
    ("mock_sites.m3_sign.app", 8013),
    ("mock_sites.m4_pdf.app", 8014),
]


def wait_ready(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok = True
        for _mod, port in APPS:
            try:
                r = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
                ok &= r.status_code == 200
            except requests.RequestException:
                ok = False
        if ok:
            return
        time.sleep(0.5)
    raise TimeoutError("仿真站启动超时")


def launch() -> list[subprocess.Popen]:
    log_dir = ROOT / "runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for mod, port in APPS:
        log = open(log_dir / f"mock_{port}.log", "w", encoding="utf-8")
        p = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", f"{mod}:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
        procs.append(p)
    wait_ready()
    return procs


if __name__ == "__main__":
    procs = launch()
    print("仿真站已启动：", [f"http://127.0.0.1:{p}" for _m, p in APPS])
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
