import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _normalize_queue_backend(value: str | None) -> str:
    backend = (value or "local").strip().lower()
    if backend in {"redis", "rq", "redis-rq", "redis_rq"}:
        return "redis_rq"
    return "local"


def _start_process(args: list[str], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(args, cwd=str(ROOT), env=env)


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the E2E backend stack.")
    parser.add_argument("--api-port", default=os.environ.get("E2E_API_PORT", "8002"))
    args = parser.parse_args()

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    backend = _normalize_queue_backend(env.get("TASK_QUEUE_BACKEND"))
    env["TASK_QUEUE_BACKEND"] = backend

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(ROOT), env=env, check=True)

    worker: subprocess.Popen | None = None
    api: subprocess.Popen | None = None
    stopping = False

    def handle_stop(signum, frame):  # noqa: ANN001
        nonlocal stopping
        stopping = True
        _stop_process(api)
        _stop_process(worker)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    try:
        if backend == "redis_rq":
            worker = _start_process([sys.executable, "scripts/run_rq_worker.py"], env)

        api = _start_process(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            env,
        )

        while not stopping:
            if api.poll() is not None:
                return int(api.returncode or 1)
            if worker is not None and worker.poll() is not None:
                print(f"RQ worker exited unexpectedly with code {worker.returncode}", file=sys.stderr)
                return int(worker.returncode or 1)
            time.sleep(1)
        return 0
    finally:
        _stop_process(api)
        _stop_process(worker)


if __name__ == "__main__":
    raise SystemExit(main())
