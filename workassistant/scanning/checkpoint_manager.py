import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.models.scan_checkpoint import ProjectScanCheckpoint
from workassistant.models.commit_sha_registry import CommitSHARegistry
from workassistant.models.file_index import FileIndex
from workassistant.config import CHECKPOINT_SAVE_INTERVAL_SECONDS, CHECKPOINT_SAVE_INTERVAL_ITEMS


class ScanCheckpointManager:
    """Database-only checkpoint manager for scan operations."""

    def __init__(self, session: AsyncSession, location_id: int, worker_id: int = 0):
        self.session = session
        self.location_id = location_id
        self.worker_id = worker_id
        self.scan_id: str = str(uuid.uuid4())
        self.checkpoint_record: Optional[ProjectScanCheckpoint] = None
        self._last_save_time: float = time.time()
        self._save_counter: int = 0

        # In-memory state (mirrors the DB record)
        self.phase: str = "discovery"
        self.projects_found: list = []
        self.projects_processed: list = []
        self.current_project: Optional[str] = None
        self.current_operation: Optional[str] = None
        self.current_commit: Optional[str] = None
        self.current_file: Optional[str] = None
        self.partial_data: dict = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load(self) -> bool:
        """Load the most recent active checkpoint for this location/worker.
        Returns True if a resumable checkpoint was found."""
        result = await self.session.execute(
            select(ProjectScanCheckpoint)
            .where(
                ProjectScanCheckpoint.location_id == self.location_id,
                ProjectScanCheckpoint.worker_id == self.worker_id,
                ProjectScanCheckpoint.is_active == True,
            )
            .order_by(ProjectScanCheckpoint.timestamp.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()

        if record is None:
            return False

        self.checkpoint_record = record
        self.scan_id = record.scan_id
        self.phase = record.phase
        self.projects_found = record.projects_found or []
        self.projects_processed = record.projects_processed or []
        self.current_project = record.current_project
        self.current_operation = record.current_operation
        self.current_commit = record.current_commit
        self.current_file = record.current_file
        self.partial_data = record.partial_data or {}
        return True

    async def save(self, force: bool = False) -> None:
        """Persist current state to DB.  Throttled by time + item count."""
        self._save_counter += 1
        now = time.time()
        time_elapsed = now - self._last_save_time
        items_threshold = self._save_counter >= CHECKPOINT_SAVE_INTERVAL_ITEMS
        time_threshold = time_elapsed >= CHECKPOINT_SAVE_INTERVAL_SECONDS

        if not force and not items_threshold and not time_threshold:
            return

        self._save_counter = 0
        self._last_save_time = now
        await self._persist()

    async def _persist(self) -> None:
        now = datetime.now(timezone.utc)
        if self.checkpoint_record is None:
            record = ProjectScanCheckpoint(
                location_id=self.location_id,
                scan_id=self.scan_id,
                phase=self.phase,
                projects_found=self.projects_found,
                projects_processed=self.projects_processed,
                current_project=self.current_project,
                current_operation=self.current_operation,
                current_commit=self.current_commit,
                current_file=self.current_file,
                timestamp=now,
                partial_data=self.partial_data,
                worker_id=self.worker_id,
                is_active=True,
            )
            self.session.add(record)
            await self.session.flush()
            self.checkpoint_record = record
        else:
            await self.session.execute(
                update(ProjectScanCheckpoint)
                .where(ProjectScanCheckpoint.id == self.checkpoint_record.id)
                .values(
                    phase=self.phase,
                    projects_found=self.projects_found,
                    projects_processed=self.projects_processed,
                    current_project=self.current_project,
                    current_operation=self.current_operation,
                    current_commit=self.current_commit,
                    current_file=self.current_file,
                    timestamp=now,
                    partial_data=self.partial_data,
                )
            )
        await self.session.commit()

    async def complete(self) -> None:
        """Mark this checkpoint as completed (inactive)."""
        if self.checkpoint_record:
            await self.session.execute(
                update(ProjectScanCheckpoint)
                .where(ProjectScanCheckpoint.id == self.checkpoint_record.id)
                .values(is_active=False)
            )
            await self.session.commit()

    # ------------------------------------------------------------------
    # State setters (call save() after changing state)
    # ------------------------------------------------------------------

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def set_current_project(self, project_path: str, operation: str) -> None:
        self.current_project = project_path
        self.current_operation = operation

    def set_current_commit(self, commit_sha: str) -> None:
        self.current_commit = commit_sha

    def set_current_file(self, file_path: str) -> None:
        self.current_file = file_path

    def mark_project_found(self, project_info) -> None:
        """Store project info dict or path string."""
        # Support both dict (new) and string (legacy) for backward compatibility
        if isinstance(project_info, dict):
            # Check if already exists by path
            path = project_info.get("path")
            if not any(p.get("path") == path if isinstance(p, dict) else p == path for p in self.projects_found):
                self.projects_found.append(project_info)
        else:
            # Legacy string path
            if project_info not in self.projects_found:
                self.projects_found.append(project_info)

    def mark_project_processed(self, project_path: str) -> None:
        if project_path not in self.projects_processed:
            self.projects_processed.append(project_path)

    def is_project_processed(self, project_path: str) -> bool:
        return project_path in self.projects_processed

    # ------------------------------------------------------------------
    # Deduplication helpers
    # ------------------------------------------------------------------

    async def is_commit_analyzed(self, commit_sha: str) -> bool:
        """Return True if this commit SHA is already in the global registry."""
        result = await self.session.execute(
            select(CommitSHARegistry).where(CommitSHARegistry.commit_sha == commit_sha)
        )
        return result.scalar_one_or_none() is not None

    async def register_commit(self, commit_sha: str, project_id: int) -> None:
        """Add commit to global SHA registry, or increment counter if already there."""
        result = await self.session.execute(
            select(CommitSHARegistry).where(CommitSHARegistry.commit_sha == commit_sha)
        )
        existing = result.scalar_one_or_none()
        if existing:
            await self.session.execute(
                update(CommitSHARegistry)
                .where(CommitSHARegistry.id == existing.id)
                .values(analysis_count=existing.analysis_count + 1)
            )
        else:
            self.session.add(CommitSHARegistry(
                commit_sha=commit_sha,
                first_project_id=project_id,
                first_seen_at=datetime.now(timezone.utc),
                analysis_count=1,
            ))

    async def is_file_indexed(self, project_id: int, file_path: str, file_hash: str) -> bool:
        """Return True if this file is already indexed with the same hash."""
        result = await self.session.execute(
            select(FileIndex).where(
                FileIndex.project_id == project_id,
                FileIndex.file_path == file_path,
                FileIndex.file_hash == file_hash,
                FileIndex.is_deleted == False,
            )
        )
        return result.scalar_one_or_none() is not None
