# -*- coding: utf-8 -*-
"""Run access-log retention from cron/CI without starting the FastAPI app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.database import db_session  # noqa: E402
from src.log_retention import run_access_log_retention  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive/delete access logs according to the configured retention policy.",
    )
    parser.add_argument(
        "--triggered-by",
        default="scheduled-job",
        help="Name stored in log_retention_runs.triggered_by.",
    )
    parser.add_argument(
        "--hot-days",
        type=int,
        default=None,
        help="Override log_retention_hot_days for this run.",
    )
    parser.add_argument(
        "--archive-days",
        type=int,
        default=None,
        help="Override log_retention_archive_days for this run.",
    )
    parser.add_argument(
        "--error-debug-days",
        type=int,
        default=None,
        help="Override error_debug_log_hot_days for this run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with db_session() as conn:
        result = run_access_log_retention(
            conn,
            triggered_by=args.triggered_by,
            hot_days=args.hot_days,
            archive_days=args.archive_days,
            error_debug_days=args.error_debug_days,
        )
        conn.commit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
