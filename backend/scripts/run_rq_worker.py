import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redis import Redis  # noqa: E402
from rq import Queue, SimpleWorker, Worker  # noqa: E402
from rq.timeouts import TimerDeathPenalty  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    connection = Redis.from_url(settings.TASK_REDIS_URL)
    queue = Queue(settings.TASK_QUEUE_NAME, connection=connection)
    worker_cls = SimpleWorker if os.name == "nt" else Worker
    worker = worker_cls([queue], connection=connection)
    worker.death_penalty_class = TimerDeathPenalty
    worker.work(with_scheduler=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
