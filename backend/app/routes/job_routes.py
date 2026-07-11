"""
Job-based SSE streaming endpoint.

GET /api/jobs/{job_id}/events?from=0
  → reconnectable SSE stream for any background job created via job_store.

The `from` query param lets the client replay missed events after a reconnect.
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth import get_current_user
from app.models import User
from app.services.job_store import job_store

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    from_index: int = Query(0, alias="from"),
    current_user: User = Depends(get_current_user),
):
    """
    Stream SSE events for a background job.

    Reconnectable: pass ?from=N to replay events starting at index N.
    The client should track the last event index it received and reconnect
    with that value on visibility change / network resume.

    Each event carries an `_idx` field so the client can track position.
    """
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    async def event_stream():
        async for event in job.iter_from(start_index=from_index):
            if event.get("type") == "keepalive":
                # SSE comment — keeps connection alive through idle proxies
                yield ": keepalive\n\n"
                continue
            # Inject the buffer index so the client can reconnect from here
            idx = len(job.events) - 1  # index of last pushed event
            payload = json.dumps({**event, "_idx": idx}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
