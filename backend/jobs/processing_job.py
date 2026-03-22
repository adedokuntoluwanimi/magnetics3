"""Cloud Run Job entrypoint for the magnetic data processing pipeline.

Reads GAIA_RUN_ID from the environment, executes the full pipeline,
and writes step-by-step status updates to Firestore as it runs.

Usage (set by Cloud Run Job definition):
    python -m backend.jobs.processing_job
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    run_id = os.environ.get("GAIA_RUN_ID")
    if not run_id:
        print("FATAL: GAIA_RUN_ID environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    from backend.config import get_settings
    from backend.gcp.firestore_store import FirestoreStore
    from backend.gcp.storage_backend import StorageBackend
    from backend.services.processing_service import ProcessingService

    settings = get_settings()
    store = FirestoreStore(settings)
    storage = StorageBackend(settings)
    service = ProcessingService(store, storage)

    try:
        service.execute_run(run_id)
    except Exception as exc:
        print(f"Processing job failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
