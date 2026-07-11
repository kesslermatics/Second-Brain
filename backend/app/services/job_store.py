"""
In-memory job store for background streaming jobs.

Solves the "stuck on tab switch / background app" problem:
  - Client POSTs → gets a job_id immediately (no open connection needed)
  - Server runs the agent/teacher task as a real asyncio.Task in the background
  - Client GETs /jobs/{job_id}/events → reconnectable SSE stream
  - All emitted events are buffered so a reconnect can replay missed events
  - Jobs auto-expire 10 minutes after completion

Flow:
  1. POST /...  → create_job() → returns job_id
  2. background asyncio.Task calls run_job(job_id, async_generator)
  3. GET /jobs/{job_id}/events → stream_job(job_id) — reconnects any time
"""

import asyncio
import time
import logging
from typing import AsyncGenerator, Any

logger = logging.getLogger(__name__)

# How long (seconds) to keep a finished job's events before expiring it
JOB_TTL_SECONDS = 600  # 10 minutes


class _Job:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.events: list[dict] = []          # buffered events (in order)
        self.done = False                     # True once the generator is exhausted
        self.error: str | None = None
        self.finished_at: float | None = None
        self._new_event = asyncio.Event()     # signalled whenever a new event is appended

    def push(self, event: dict) -> None:
        self.events.append(event)
        self._new_event.set()
        self._new_event.clear()

    def finish(self, error: str | None = None) -> None:
        self.done = True
        self.error = error
        self.finished_at = time.monotonic()
        self._new_event.set()   # wake any waiting consumers

    async def iter_from(self, start_index: int = 0) -> AsyncGenerator[dict, None]:
        """Yield buffered events from start_index, then tail new ones as they arrive."""
        idx = start_index
        while True:
            # Drain everything buffered since last check
            while idx < len(self.events):
                yield self.events[idx]
                idx += 1

            if self.done:
                return

            # Wait for the next event (or job completion)
            try:
                await asyncio.wait_for(self._new_event.wait(), timeout=25.0)
            except asyncio.TimeoutError:
                # Send a keepalive comment so the connection stays open through
                # proxies that close idle streams.
                yield {"type": "keepalive"}


class JobStore:
    """Singleton in-process store.  Not shared across workers — fine for a
    single-worker deployment (Docker / uvicorn with 1 worker)."""

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}

    def create_job(self, job_id: str) -> _Job:
        job = _Job(job_id)
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> _Job | None:
        return self._jobs.get(job_id)

    async def run_job(self, job_id: str, gen: AsyncGenerator[dict, Any]) -> None:
        """Drive *gen* to completion, pushing every event into the job buffer.
        Designed to be called as a fire-and-forget asyncio.Task."""
        job = self._jobs.get(job_id)
        if job is None:
            logger.warning("run_job: job %s not found", job_id)
            return
        try:
            async for event in gen:
                job.push(event)
        except Exception as exc:
            logger.exception("Job %s failed: %s", job_id, exc)
            job.finish(error=str(exc))
        else:
            job.finish()
        self._evict_old_jobs()

    def _evict_old_jobs(self) -> None:
        now = time.monotonic()
        to_delete = [
            jid for jid, j in self._jobs.items()
            if j.done and j.finished_at is not None
            and (now - j.finished_at) > JOB_TTL_SECONDS
        ]
        for jid in to_delete:
            del self._jobs[jid]


# Module-level singleton
job_store = JobStore()
