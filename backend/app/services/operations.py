import os
import shutil
import time
from collections import Counter, deque
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import Settings
from app.utils.time import utc_now


class RequestMetrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = Lock()
        self.total_requests = 0
        self.status_counts: Counter[str] = Counter()
        self.path_counts: Counter[str] = Counter()
        self.recent_durations: deque[float] = deque(maxlen=500)

    def record(self, *, method: str, path: str, status_code: int, duration_ms: float) -> None:
        route = f"{method} {path}"
        with self._lock:
            self.total_requests += 1
            self.status_counts[str(status_code)] += 1
            self.path_counts[route] += 1
            self.recent_durations.append(duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = list(self.recent_durations)
            avg = round(sum(durations) / len(durations), 2) if durations else 0
            p95 = round(sorted(durations)[int(len(durations) * 0.95) - 1], 2) if durations else 0
            return {
                "uptime_seconds": int(time.time() - self.started_at),
                "total_requests": self.total_requests,
                "status_counts": dict(self.status_counts),
                "top_paths": [
                    {"path": path, "count": count}
                    for path, count in self.path_counts.most_common(10)
                ],
                "avg_duration_ms": avg,
                "p95_duration_ms": p95,
            }


request_metrics = RequestMetrics()


def _sqlite_path(database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url.removeprefix(prefix)).resolve()


def build_backup_status(settings: Settings) -> dict[str, Any]:
    backup_dir = Path(settings.BACKUP_DIR)
    backups = sorted(backup_dir.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True) if backup_dir.exists() else []
    latest = backups[0] if backups else None
    return {
        "enabled": settings.BACKUP_ENABLED,
        "backup_dir": str(backup_dir),
        "retention_days": settings.BACKUP_RETENTION_DAYS,
        "latest_backup": None
        if not latest
        else {
            "filename": latest.name,
            "size_bytes": latest.stat().st_size,
            "created_at": utc_now().fromtimestamp(latest.stat().st_mtime).isoformat(),
        },
        "backup_count": len(backups),
        "database_supported": _sqlite_path(settings.DATABASE_URL) is not None,
    }


def create_sqlite_backup(settings: Settings) -> dict[str, Any]:
    source = _sqlite_path(settings.DATABASE_URL)
    if not source or not source.exists():
        raise RuntimeError("当前数据库不是可直接备份的本地 SQLite 文件")

    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    filename = f"interview_agent_{utc_now().strftime('%Y%m%d_%H%M%S')}.db"
    target = backup_dir / filename
    shutil.copy2(source, target)

    cutoff = time.time() - max(settings.BACKUP_RETENTION_DAYS, 1) * 86400
    for candidate in backup_dir.glob("*.db"):
        if candidate.stat().st_mtime < cutoff:
            try:
                candidate.unlink()
            except OSError:
                pass

    return {
        "filename": target.name,
        "path": str(target),
        "size_bytes": os.path.getsize(target),
        "created_at": utc_now().isoformat(),
    }
