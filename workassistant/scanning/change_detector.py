import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.models.project import Project
from workassistant.models.file_index import FileIndex
from workassistant.config import MAX_FILE_SIZE_BYTES, SCAN_IGNORE_PATTERNS


class ChangeDetector:
    """Detects which projects and files have changed since last scan."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Project-level change detection
    # ------------------------------------------------------------------

    def has_new_commits(self, project: Project, latest_commit_hash: Optional[str]) -> bool:
        """True when the repo HEAD differs from the last analyzed commit."""
        if latest_commit_hash is None:
            return False
        return latest_commit_hash != project.last_analyzed_commit_hash

    async def get_indexed_files(self, project_id: int) -> Dict[str, str]:
        """Return {relative_path: file_hash} for all non-deleted indexed files."""
        result = await self.session.execute(
            select(FileIndex).where(
                FileIndex.project_id == project_id,
                FileIndex.is_deleted == False,
            )
        )
        return {row.file_path: row.file_hash for row in result.scalars().all()}

    # ------------------------------------------------------------------
    # File-level scanning
    # ------------------------------------------------------------------

    def scan_files(self, project_path: str) -> Dict[str, str]:
        """Walk project directory, return {relative_path: sha256_hash}.
        Skips files over MAX_FILE_SIZE_BYTES, binary files, and ignored dirs."""
        root = Path(project_path)
        files: Dict[str, str] = {}

        for file_path in self._walk_files(root):
            rel = str(file_path.relative_to(root))
            try:
                file_hash = self._compute_hash(file_path)
                files[rel] = file_hash
            except (OSError, PermissionError):
                continue

        return files

    def _walk_files(self, root: Path):
        """Recursively yield file paths, pruning ignored directories."""
        try:
            for entry in root.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if self._should_ignore_dir(entry.name):
                        continue
                    yield from self._walk_files(entry)
                elif entry.is_file():
                    if self._should_skip_file(entry):
                        continue
                    yield entry
        except (PermissionError, OSError):
            return

    def _should_ignore_dir(self, name: str) -> bool:
        for pattern in SCAN_IGNORE_PATTERNS:
            if pattern and name == pattern.strip():
                return True
        return False

    def _should_skip_file(self, path: Path) -> bool:
        try:
            if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                return True
        except (OSError, PermissionError):
            return True
        if self._is_binary(path):
            return True
        return False

    @staticmethod
    def _is_binary(path: Path) -> bool:
        """Quick binary detection: read first 8 KB and look for null bytes."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
            return b"\x00" in chunk
        except (OSError, PermissionError):
            return True

    @staticmethod
    def _compute_hash(path: Path) -> str:
        """Compute SHA-256 of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Detect all changes for a project
    # ------------------------------------------------------------------

    async def detect_changes(self, project: Project) -> dict:
        """Compare current filesystem state against indexed state.
        Returns a summary dict with modified/deleted/added file lists."""
        indexed = await self.get_indexed_files(project.id)
        current = self.scan_files(project.path)

        added = [p for p in current if p not in indexed]
        modified = [p for p in current if p in indexed and current[p] != indexed[p]]
        deleted = [p for p in indexed if p not in current]

        return {
            "has_changes": bool(added or modified or deleted),
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "current_files": current,
        }
