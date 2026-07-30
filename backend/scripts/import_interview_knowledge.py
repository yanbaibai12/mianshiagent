import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session_maker, init_db  # noqa: E402
from app.services.interview_question_bank import DEFAULT_INTERVIEW_BANK, import_interview_question_bank  # noqa: E402


async def import_bank(path: Path, *, skip_vector: bool, recreate_vector: bool) -> dict[str, Any]:
    await init_db()
    async with async_session_maker() as db:
        return await import_interview_question_bank(
            db,
            path=path,
            skip_vector=skip_vector,
            recreate_vector=recreate_vector,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Import structured Agent interview question cards into the knowledge base.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_INTERVIEW_BANK))
    parser.add_argument("--skip-vector", action="store_true")
    parser.add_argument("--recreate-vector", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(import_bank(Path(args.path).resolve(), skip_vector=args.skip_vector, recreate_vector=args.recreate_vector))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
