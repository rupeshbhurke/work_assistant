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
        logger.info(f"Running hierarchical scan job {job_id}")
        await self._update_job(job_id, status="running", phase="discovery")

        try:
            # Phase 1: Discovery - find all projects
            from pathlib import Path
            from workassistant.models.project_location import ProjectLocation
            
            async with async_session_maker() as session:
                result = await session.execute(
                    select(ProjectLocation).where(ProjectLocation.id == location_id)
                )
                location = result.scalar_one_or_none()
                if not location:
                    raise Exception(f"Location {location_id} not found")
                
                root = Path(location.path).expanduser().resolve()
                if not root.exists():
                    raise Exception(f"Location path does not exist: {root}")
            
            # Discover projects
            logger.info(f"Discovering projects at {root}")
            discovered_projects = await self._discover_projects(root)
            
            await self._update_job(
                job_id,
                phase="spawning",
                progress_percent=20,
                projects_total=len(discovered_projects),
            )
            
            logger.info(f"Discovered {len(discovered_projects)} projects, spawning child jobs")
            
            # Phase 2: Spawn project scan jobs
            from workassistant.jobs.project_scan_job_manager import project_scan_job_manager
            
            project_job_ids = []
            for project in discovered_projects:
                child_job_id = await project_scan_job_manager.start_project_scan(
                    parent_job_id=job_id,
                    project_path=project["path"],
                    project_name=project["name"],
                    project_type=project["project_type"],
                )
                project_job_ids.append(child_job_id)
            
            await self._update_job(
                job_id,
                phase="monitoring",
                progress_percent=30,
            )
            
            logger.info(f"Spawned {len(project_job_ids)} child jobs, monitoring progress")
            
            # Phase 3: Monitor child jobs until completion
            await self._monitor_child_jobs(job_id, project_job_ids)
            
            # Phase 4: Aggregate results
            result_summary = await self._aggregate_results(job_id)
            
            end_time = datetime.now(timezone.utc)
            await self._update_job(
                job_id,
                status="completed",
                progress_percent=100,
                phase="done",
                end_time=end_time,
                result_summary=result_summary,
            )
            logger.info(f"Hierarchical scan job {job_id} completed: {result_summary}")
            final = {"status": "completed", "progress_percent": 100, "result_summary": result_summary}
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
    # Hierarchical job helpers
    # ------------------------------------------------------------------

    async def _discover_projects(self, root: Path) -> list:
        """Discover all projects in a location."""
        from workassistant.config import SCAN_IGNORE_PATTERNS
        
        discovered = []
        
        def walk_directories(path: Path):
            """Recursively find projects."""
            try:
                entries = [e for e in path.iterdir() if e.is_dir() and not e.is_symlink()]
            except (PermissionError, OSError):
                return
            
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if any(pat.strip() and entry.name == pat.strip() for pat in SCAN_IGNORE_PATTERNS):
                    continue
                
                if (entry / ".git").exists():
                    discovered.append({
                        "path": str(entry),
                        "name": entry.name,
                        "project_type": "git"
                    })
                else:
                    # Check if this has sub-git repos
                    has_sub_git = any(
                        (sub / ".git").exists()
                        for sub in entry.iterdir()
                        if sub.is_dir() and not sub.name.startswith(".")
                    ) if entry.is_dir() else False
                    
                    if has_sub_git:
                        walk_directories(entry)
                    else:
                        discovered.append({
                            "path": str(entry),
                            "name": entry.name,
                            "project_type": "plain"
                        })
        
        walk_directories(root)
        return discovered

    async def _monitor_child_jobs(self, parent_job_id: str, child_job_ids: list) -> None:
        """Monitor child jobs until all complete."""
        from workassistant.models.project_scan_job import ProjectScanJob
        
        while True:
            async with async_session_maker() as session:
                # Get current status of all child jobs
                result = await session.execute(
                    select(ProjectScanJob).where(
                        ProjectScanJob.parent_job_id == parent_job_id
                    )
                )
                children = result.scalars().all()
                
                if not children:
                    break
                
                # Check if all are done
                statuses = [c.status for c in children]
                if all(s in ("completed", "failed", "cancelled") for s in statuses):
                    break
                
                # Calculate overall progress
                total_progress = sum(c.progress_percent for c in children)
                avg_progress = int(30 + (total_progress / len(children)) * 0.7) if children else 30
                
                await self._update_job(
                    parent_job_id,
                    progress_percent=avg_progress,
                )
            
            # Wait before checking again
            await asyncio.sleep(2)

    async def _aggregate_results(self, parent_job_id: str) -> dict:
        """Aggregate results from all child jobs."""
        from workassistant.models.project_scan_job import ProjectScanJob
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanJob).where(
                    ProjectScanJob.parent_job_id == parent_job_id
                )
            )
            children = result.scalars().all()
            
            summary = {
                "total_projects": len(children),
                "completed": sum(1 for c in children if c.status == "completed"),
                "failed": sum(1 for c in children if c.status == "failed"),
                "cancelled": sum(1 for c in children if c.status == "cancelled"),
                "total_commits": sum(c.commits_processed or 0 for c in children),
                "total_files": sum(c.files_processed or 0 for c in children),
                "total_duration": sum(c.duration_seconds or 0 for c in children),
                "errors": [c.error_message for c in children if c.error_message],
            }
            
            return summary

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
