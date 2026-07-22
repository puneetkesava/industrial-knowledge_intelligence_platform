#!/usr/bin/env python3
"""Re-enqueue uploaded (not yet indexed) documents without duplicating rows.

Usage (inside API/worker container or with DATABASE_URL set):

  python -m scripts.reenqueue_uploaded --limit 50 --async-worker
  python scripts/reenqueue_uploaded.py --limit 100 --status uploaded

Also promotes already-chunked documents that have indexed chunks to status=ready
so the dashboard reflects prior successful indexing.
"""

from __future__ import annotations

import argparse
import sys


def promote_chunked_to_ready(session) -> int:
    """Mark documents with indexed chunks as ready (no re-processing)."""
    from sqlalchemy import text

    result = session.execute(
        text(
            """
            UPDATE documents d
            SET status = 'ready'
            WHERE d.status IN ('chunked', 'parsed', 'indexed')
              AND EXISTS (
                SELECT 1 FROM document_chunks c
                WHERE c.document_id = d.id AND c.status = 'indexed'
              )
            """
        )
    )
    session.commit()
    return int(result.rowcount or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--status",
        action="append",
        dest="statuses",
        default=None,
        help="Document status to enqueue (repeatable). Default: uploaded",
    )
    parser.add_argument("--hero-only", action="store_true", default=False)
    parser.add_argument("--async-worker", action="store_true", default=True)
    parser.add_argument("--sync-plan-only", action="store_true", default=False)
    parser.add_argument(
        "--promote-ready",
        action="store_true",
        default=True,
        help="Promote chunked docs with indexed chunks to ready (default on)",
    )
    parser.add_argument("--no-promote-ready", action="store_true", default=False)
    args = parser.parse_args(argv)

    from app.db.session import get_session_factory
    from app.indexing.status_service import IndexingStatusService

    statuses = args.statuses or ["uploaded"]
    async_worker = False if args.sync_plan_only else args.async_worker

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        promoted = 0
        if args.promote_ready and not args.no_promote_ready:
            promoted = promote_chunked_to_ready(session)
            print(f"promoted_to_ready={promoted}")

        svc = IndexingStatusService(session)
        result = svc.enqueue_priority(
            hero_only=args.hero_only,
            limit=args.limit,
            async_worker=async_worker,
            status_filter=statuses,
        )
        session.commit()
        queued = result.get("queued") or []
        print(f"enqueued={len(queued)} statuses={statuses} async={async_worker}")
        for item in queued[:10]:
            print(f"  {item.get('document_id')} task={item.get('task_id', 'planned')}")
        if len(queued) > 10:
            print(f"  ... and {len(queued) - 10} more")
    return 0


if __name__ == "__main__":
    # Ensure /app is on path when run as script inside container
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    raise SystemExit(main())
