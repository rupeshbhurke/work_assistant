"""FastAPI router for async scan operations and WebSocket progress."""
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from workassistant.jobs.scan_job_manager import scan_job_manager
from workassistant.jobs.websocket_manager import websocket_manager
from workassistant.database import async_session_maker
from workassistant.models.project_location import ProjectLocation
from sqlalchemy import select
from pathlib import Path

router = APIRouter(prefix="/api/scan", tags=["scan"])


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class StartScanRequest(BaseModel):
    location_path: Optional[str] = None
    location_id: Optional[int] = None
    incremental: bool = True


class StartScanResponse(BaseModel):
    job_id: str
    status: str
    message: str


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@router.post("/start", response_model=StartScanResponse)
async def start_scan(req: StartScanRequest):
    """Start a background scan job. Returns job_id immediately."""
    location_id: Optional[int] = req.location_id

    if location_id is None and req.location_path:
        location_path = str(Path(req.location_path).expanduser().resolve())
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectLocation).where(ProjectLocation.path == location_path)
            )
            record = result.scalar_one_or_none()
            if not record:
                record = ProjectLocation(
                    path=location_path,
                    is_primary=False,
                    is_active=True,
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)
            location_id = record.id

    if location_id is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Either location_path or location_id required")

    job_id = await scan_job_manager.start_scan(
        location_id=location_id,
        incremental=req.incremental,
    )
    return StartScanResponse(
        job_id=job_id,
        status="started",
        message=f"Scan job {job_id} started in background",
    )


@router.get("/status/{job_id}")
async def get_scan_status(job_id: str):
    """Poll the status of a scan job."""
    return await scan_job_manager.get_status(job_id)


@router.post("/cancel/{job_id}")
async def cancel_scan(job_id: str):
    """Cancel a running scan job."""
    cancelled = await scan_job_manager.cancel(job_id)
    return {"job_id": job_id, "cancelled": cancelled}


@router.get("/jobs")
async def list_scan_jobs(limit: int = 20):
    """List recent scan jobs."""
    return await scan_job_manager.list_recent(limit=limit)


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------

@router.websocket("/ws/{job_id}")
async def websocket_scan_progress(websocket: WebSocket, job_id: str):
    """Real-time scan progress stream for a job."""
    await websocket_manager.connect(websocket, job_id)
    # Send current status immediately on connect
    status = await scan_job_manager.get_status(job_id)
    if "error" not in status:
        await websocket.send_json(status)
    try:
        while True:
            # Keep connection alive; server pushes progress via broadcast
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket, job_id)
