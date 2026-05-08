"""
Project-level scan job manager for hierarchical job system.
Manages individual project scanning jobs spawned by location scan jobs.
"""
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

from sqlalchemy import select, update

from workassistant.database import async_session_maker
from workassistant.models.project_scan_job import ProjectScanJob
from workassistant.models.scan_job import ScanJob
from workassistant.jobs.websocket_manager import websocket_manager


class ProjectScanJobManager:
    """Manages individual project scan jobs."""

    def __init__(self):
        # job_id -> asyncio.Task
        self._active: Dict[str, asyncio.Task] = {}

    async def start_project_scan(
        self,
        parent_job_id: str,
        project_path: str,
        project_name: str,
        project_type: str,
        project_id: Optional[int] = None,
    ) -> str:
        """
        Create a ProjectScanJob record and launch background task.
        Returns job_id immediately.
        """
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with async_session_maker() as session:
            job = ProjectScanJob(
                job_id=job_id,
                parent_job_id=parent_job_id,
                project_id=project_id,
                project_path=project_path,
                project_name=project_name,
                project_type=project_type,
                status="pending",
                phase="metadata",
                progress_percent=0,
                commits_processed=0,
                files_processed=0,
                retry_count=0,
                max_retries=3,
            )
            session.add(job)
            await session.commit()

        # Update parent job child count
        await self._increment_parent_child_count(parent_job_id, "total")

        task = asyncio.create_task(
            self._run_project_job(job_id, project_path, project_type),
            name=f"project-scan-{job_id[:8]}",
        )
        self._active[job_id] = task
        task.add_done_callback(lambda _: self._active.pop(job_id, None))
        
        logger.info(f"Started project scan job {job_id} for {project_name}")
        return job_id

    async def get_status(self, job_id: str) -> dict:
        """Get status of a project scan job."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanJob).where(ProjectScanJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return {"error": "Job not found"}
            return self._job_to_dict(job)

    async def list_by_parent(self, parent_job_id: str) -> list:
        """List all project jobs for a parent location scan job."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanJob)
                .where(ProjectScanJob.parent_job_id == parent_job_id)
                .order_by(ProjectScanJob.created_at.asc())
            )
            return [self._job_to_dict(j) for j in result.scalars().all()]

    async def restart_failed_job(self, job_id: str) -> Optional[str]:
        """
        Restart a failed project scan job.
        Creates a new job with same parameters but reset retry count.
        """
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanJob).where(ProjectScanJob.job_id == job_id)
            )
            old_job = result.scalar_one_or_none()
            
            if not old_job:
                return None
            
            if old_job.status not in ("failed", "cancelled"):
                logger.warning(f"Cannot restart job {job_id} with status {old_job.status}")
                return None
            
            # Create new job
            new_job_id = await self.start_project_scan(
                parent_job_id=old_job.parent_job_id,
                project_path=old_job.project_path,
                project_name=old_job.project_name,
                project_type=old_job.project_type,
                project_id=old_job.project_id,
            )
            
            logger.info(f"Restarted job {job_id} as {new_job_id}")
            return new_job_id

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running project scan job."""
        task = self._active.get(job_id)
        if task and not task.done():
            task.cancel()

        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanJob).where(ProjectScanJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if job and job.status in ("pending", "running"):
                await session.execute(
                    update(ProjectScanJob)
                    .where(ProjectScanJob.job_id == job_id)
                    .values(
                        status="cancelled",
                        end_time=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                
                # Update parent job
                await self._increment_parent_child_count(job.parent_job_id, "failed")
                
                return True
        return False

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    async def _run_project_job(
        self,
        job_id: str,
        project_path: str,
        project_type: str,
    ) -> None:
        """Run the actual project scan."""
        logger.info(f"Running project scan job {job_id} for {project_path}")
        
        # Get parent job ID for updates
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanJob).where(ProjectScanJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return
            parent_job_id = job.parent_job_id
        
        await self._update_job(job_id, status="running", start_time=datetime.now(timezone.utc))
        await self._increment_parent_child_count(parent_job_id, "running")

        try:
            # Import here to avoid circular dependency
            from workassistant.scanning.project_processor import process_single_project
            
            result = await process_single_project(
                project_path=Path(project_path),
                project_type=project_type,
                progress_callback=lambda p: self._project_progress_callback(job_id, parent_job_id, p),
            )

            end_time = datetime.now(timezone.utc)
            await self._update_job(
                job_id,
                status="completed",
                progress_percent=100,
                phase="done",
                end_time=end_time,
                result_summary=result,
            )
            
            # Update parent counters
            await self._decrement_parent_child_count(parent_job_id, "running")
            await self._increment_parent_child_count(parent_job_id, "completed")
            
            logger.info(f"Project scan job {job_id} completed: {result}")

        except asyncio.CancelledError:
            logger.warning(f"Project scan job {job_id} cancelled")
            await self._update_job(job_id, status="cancelled", end_time=datetime.now(timezone.utc))
            await self._decrement_parent_child_count(parent_job_id, "running")
            await self._increment_parent_child_count(parent_job_id, "failed")
            
        except Exception as exc:
            logger.error(f"Project scan job {job_id} failed: {exc}", exc_info=True)
            
            # Check if we should retry
            async with async_session_maker() as session:
                result = await session.execute(
                    select(ProjectScanJob).where(ProjectScanJob.job_id == job_id)
                )
                job = result.scalar_one_or_none()
                
                if job and job.retry_count < job.max_retries:
                    # Retry with exponential backoff
                    retry_count = job.retry_count + 1
                    backoff_seconds = min(2 ** retry_count, 300)  # Max 5 minutes
                    
                    logger.info(f"Retrying job {job_id} in {backoff_seconds}s (attempt {retry_count}/{job.max_retries})")
                    
                    await self._update_job(
                        job_id,
                        retry_count=retry_count,
                        error_message=f"Retry {retry_count}: {str(exc)}",
                    )
                    
                    await asyncio.sleep(backoff_seconds)
                    
                    # Restart the job
                    await self._update_job(job_id, status="running", phase="metadata")
                    await self._run_project_job(job_id, project_path, project_type)
                else:
                    # Max retries reached or no retry allowed
                    await self._update_job(
                        job_id,
                        status="failed",
                        error_message=str(exc),
                        end_time=datetime.now(timezone.utc),
                    )
                    
                    await self._decrement_parent_child_count(parent_job_id, "running")
                    await self._increment_parent_child_count(parent_job_id, "failed")

    async def _project_progress_callback(self, job_id: str, parent_job_id: str, progress: dict) -> None:
        """Handle progress updates from project processor."""
        await self._update_job(
            job_id,
            phase=progress.get("phase"),
            progress_percent=progress.get("progress_percent", 0),
            commits_total=progress.get("commits_total"),
            commits_processed=progress.get("commits_processed", 0),
            files_total=progress.get("files_total"),
            files_processed=progress.get("files_processed", 0),
        )
        
        # Broadcast to websocket
        progress["job_id"] = job_id
        progress["parent_job_id"] = parent_job_id
        await websocket_manager.broadcast(job_id, progress)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _update_job(self, job_id: str, **values) -> None:
        """Update project scan job fields."""
        values["updated_at"] = datetime.now(timezone.utc)
        
        if "end_time" in values and values.get("end_time"):
            async with async_session_maker() as session:
                result = await session.execute(
                    select(ProjectScanJob).where(ProjectScanJob.job_id == job_id)
                )
                job = result.scalar_one_or_none()
                if job and job.start_time:
                    elapsed = (values["end_time"] - job.start_time).total_seconds()
                    values["duration_seconds"] = int(elapsed)

        async with async_session_maker() as session:
            await session.execute(
                update(ProjectScanJob).where(ProjectScanJob.job_id == job_id).values(**values)
            )
            await session.commit()

    async def _increment_parent_child_count(self, parent_job_id: str, counter: str) -> None:
        """Increment a child counter on the parent job."""
        field_map = {
            "total": "child_jobs_total",
            "completed": "child_jobs_completed",
            "failed": "child_jobs_failed",
            "running": "child_jobs_running",
        }
        
        field = field_map.get(counter)
        if not field:
            return
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(ScanJob).where(ScanJob.job_id == parent_job_id)
            )
            job = result.scalar_one_or_none()
            if job:
                current_value = getattr(job, field, 0)
                await session.execute(
                    update(ScanJob)
                    .where(ScanJob.job_id == parent_job_id)
                    .values(**{field: current_value + 1, "updated_at": datetime.now(timezone.utc)})
                )
                await session.commit()

    async def _decrement_parent_child_count(self, parent_job_id: str, counter: str) -> None:
        """Decrement a child counter on the parent job."""
        field_map = {
            "running": "child_jobs_running",
        }
        
        field = field_map.get(counter)
        if not field:
            return
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(ScanJob).where(ScanJob.job_id == parent_job_id)
            )
            job = result.scalar_one_or_none()
            if job:
                current_value = getattr(job, field, 0)
                await session.execute(
                    update(ScanJob)
                    .where(ScanJob.job_id == parent_job_id)
                    .values(**{field: max(0, current_value - 1), "updated_at": datetime.now(timezone.utc)})
                )
                await session.commit()

    @staticmethod
    def _job_to_dict(job: ProjectScanJob) -> dict:
        """Convert ProjectScanJob to dictionary."""
        return {
            "job_id": job.job_id,
            "parent_job_id": job.parent_job_id,
            "project_id": job.project_id,
            "project_path": job.project_path,
            "project_name": job.project_name,
            "project_type": job.project_type,
            "status": job.status,
            "phase": job.phase,
            "progress_percent": job.progress_percent,
            "commits_total": job.commits_total,
            "commits_processed": job.commits_processed,
            "files_total": job.files_total,
            "files_processed": job.files_processed,
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "start_time": job.start_time.isoformat() if job.start_time else None,
            "end_time": job.end_time.isoformat() if job.end_time else None,
            "duration_seconds": job.duration_seconds,
            "error_message": job.error_message,
            "result_summary": job.result_summary,
        }


# Singleton
project_scan_job_manager = ProjectScanJobManager()
