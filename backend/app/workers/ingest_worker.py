"""Long-running ingestion worker.

    python -m app.workers.ingest_worker

Run as many replicas as you like: ``FOR UPDATE SKIP LOCKED`` guarantees they claim
disjoint rows. SIGTERM/SIGINT finish the current batch and exit cleanly.
"""

from __future__ import annotations

import logging
import signal
import socket
import threading
import uuid

from app.core.config import get_settings
from app.db.engines import get_registry
from app.services.ingestion_service import IngestionService

log = logging.getLogger("omnidata.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    service = IngestionService(get_registry(), settings, worker_id=worker_id)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    log.info("Worker %s started (batch=%d, poll=%.1fs)", worker_id, settings.worker_batch_size, settings.worker_poll_seconds)
    while not stop.is_set():
        try:
            outcome = service.run(max_batches=5)
            idle = outcome.claimed == 0
        except Exception:
            log.exception("Ingestion cycle failed; retrying after back-off")
            idle = True
        if idle:
            stop.wait(settings.worker_poll_seconds)
    log.info("Worker %s stopped", worker_id)
    get_registry().dispose()


if __name__ == "__main__":
    main()
