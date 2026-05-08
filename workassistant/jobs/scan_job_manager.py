"""
Background scan job lifecycle manager.
Each job gets its own DB session; the manager only stores asyncio.Task references.
"""
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

from sqlalchemy import select, update

from workassistant.database import async_session_maker
from workassistant.models.scan_job import ScanJob
from workassistant.jobs.websocket_manager import websocket_manager
from workassistant.scanning.scanner import ProjectScanner


class ScanJobManager:
    """Creates, tracks, and cancels background scan jobs."""

    def __init__(self):
        # job_id -> asyncio.Task
        self._active: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_scan(
        self,
        location_id: int,
        created_by: Optional[str] = None,
        incremental: bool = True,
    ) -> str:
        """Create a ScanJob record and launch background task.
        Returns job_id immediately."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with async_session_maker() as session:
            job = ScanJob(
                job_id=job_id,
                location_id=location_id,
                status="pending",
                phase="discovery",
                progress_percent=0,
                projects_processed=0,
                commits_processed=0,
                files_processed=0,
                start_time=now,
                created_by=created_by,
            )
            session.add(job)
            await session.commit()

        task = asyncio.create_task(
            self._run_job(job_id, location_id, incremental),
            name=f"scan-job-{job_id[:8]}",
        )
        self._active[job_id] = task
        task.add_done_callback(lambda _: self._active.pop(job_id, None))
        logger.info(f"Started scan job {job_id} for location_id={location_id}, incremental={incremental}")
        return job_id

    async def get_status(self, job_id: str) -> dict:
        async with async_session_maker() as session:
            result = await session.execute(
                select(ScanJob).where(ScanJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return {"error": "Job not found"}
            return self._job_to_dict(job)

    async def cancel(self, job_id: str) -> bool:
        task = self._active.get(job_id)
        if task and not task.done():
            task.cancel()

        async with async_session_maker() as session:
            result = await session.execute(
                select(ScanJob).where(ScanJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if job and job.status in ("pending", "running"):
                await session.execute(
                    update(ScanJob)
                    .where(ScanJob.job_id == job_id)
                    .values(
                        status="cancelled",
                        end_time=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                return True
        return False

    async def list_recent(self, limit: int = 20) -> list:
        async with async_session_maker() as session:
            result = await session.execute(
                select(ScanJob).order_by(ScanJob.created_at.desc()).limit(limit)
            )
            return [self._job_to_dict(j) for j in result.scalars().all()]

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    async def _run_job(
        self,
        job_id: str,
        location_id: int,
        incremental: bool,
    ) -> None:
        logger.info(f"Running scan job {job_id}")
        await self._update_job(job_id, status="running")

        async def progress_cb(progress: dict) -> None:
            await self._update_job(
                job_id,
                phase=progress.get("phase"),
                progress_percent=progress.get("progress_percent", 0),
                current_project=progress.get("current_project"),
                projects_total=progress.get("projects_total"),
                projects_processed=progress.get("projects_processed", 0),
                commits_total=progress.get("commits_total"),
                commits_processed=progress.get("commits_processed", 0),
                files_total=progress.get("files_total"),
                files_processed=progress.get("files_processed", 0),
            )
            await websocket_manager.broadcast(job_id, progress)

        try:
            scanner = ProjectScanner(
                location_id=location_id,
                worker_id=0,
                progress_callback=progress_cb,
                incremental=incremental,
            )
            result = await scanner.run()

            end_time = datetime.now(timezone.utc)
            await self._update_job(
                job_id,
                status="completed",
                progress_percent=100,
                phase="done",
                end_time=end_time,
                result_summary=result,
            )
            logger.info(f"Scan job {job_id} completed: {result}")
            final = {"status": "completed", "progress_percent": 100, "result_summary": result}
            await websocket_manager.broadcast(job_id, final)

        except asyncio.CancelledError:
            logger.warning(f"Scan job {job_id} cancelled")
            await self._update_job(job_id, status="cancelled", end_time=datetime.now(timezone.utc))
        except Exception as exc:
            logger.error(f"Scan job {job_id} failed: {exc}", exc_info=True)
            await self._update_job(
                job_id,
                status="failed",
                error_message=str(exc),
                end_time=datetime.now(timezone.utc),
            )
            err_payload = {"status": "failed", "error_message": str(exc)}
            await websocket_manager.broadcast(job_id, err_payload)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _update_job(self, job_id: str, **values) -> None:
        values["updated_at"] = datetime.now(timezone.utc)
        if "end_time" in values and values.get("end_time"):
            async with async_session_maker() as session:
                result = await session.execute(
                    select(ScanJob).where(ScanJob.job_id == job_id)
                )
                job = result.scalar_one_or_none()
                if job and job.start_time:
                    elapsed = (values["end_time"] - job.start_time).total_seconds()
                    values["duration_seconds"] = int(elapsed)

        async with async_session_maker() as session:
            await session.execute(
                update(ScanJob).where(ScanJob.job_id == job_id).values(**values)
            )
            await session.commit()

    @staticmethod
    def _job_to_dict(job: ScanJob) -> dict:
        return {
            "job_id": job.job_id,
            "location_id": job.location_id,
            "status": job.status,
            "phase": job.phase,
            "progress_percent": job.progress_percent,
            "current_project": job.current_project,
            "projects_total": job.projects_total,
            "projects_processed": job.projects_processed,
            "commits_total": job.commits_total,
            "commits_processed": job.commits_processed,
            "files_total": job.files_total,
            "files_processed": job.files_processed,
            "start_time": job.start_time.isoformat() if job.start_time else None,
            "end_time": job.end_time.isoformat() if job.end_time else None,
            "duration_seconds": job.duration_seconds,
            "error_message": job.error_message,
            "result_summary": job.result_summary,
        }


# Singleton
scan_job_manager = ScanJobManager()
