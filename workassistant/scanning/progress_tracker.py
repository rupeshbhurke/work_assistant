import time
from typing import Optional, Callable, Awaitable


class ScanProgressTracker:
    """Tracks multi-phase scan progress and computes metrics."""

    PHASES = ["discovery", "metadata", "commit_analysis", "indexing"]

    def __init__(
        self,
        total_projects: int = 0,
        total_commits: int = 0,
        total_files: int = 0,
        progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.total_projects = total_projects
        self.total_commits = total_commits
        self.total_files = total_files
        self.progress_callback = progress_callback

        self.current_phase: str = "discovery"
        self.current_project: Optional[str] = None
        self.current_operation: Optional[str] = None

        self.projects_processed: int = 0
        self.commits_processed: int = 0
        self.files_processed: int = 0
        self.commits_skipped_duplicate: int = 0
        self.commits_skipped_old: int = 0
        self.ai_calls_made: int = 0
        self.ai_cost_usd: float = 0.0

        self.start_time: float = time.time()
        self._last_callback_time: float = 0.0
        self._callback_interval: float = 2.0  # seconds between callbacks

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_phase(self, phase: str) -> None:
        self.current_phase = phase

    def set_totals(self, projects: int = 0, commits: int = 0, files: int = 0) -> None:
        if projects:
            self.total_projects = projects
        if commits:
            self.total_commits = commits
        if files:
            self.total_files = files

    def set_current_project(self, name: str, operation: str = "") -> None:
        self.current_project = name
        self.current_operation = operation

    def increment_projects(self) -> None:
        self.projects_processed += 1

    def increment_commits(self, skipped_dup: bool = False, skipped_old: bool = False) -> None:
        self.commits_processed += 1
        if skipped_dup:
            self.commits_skipped_duplicate += 1
        if skipped_old:
            self.commits_skipped_old += 1

    def increment_files(self) -> None:
        self.files_processed += 1

    def add_ai_cost(self, cost_usd: float) -> None:
        self.ai_calls_made += 1
        self.ai_cost_usd += cost_usd

    # ------------------------------------------------------------------
    # Computed metrics
    # ------------------------------------------------------------------

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def progress_percent(self) -> int:
        """Overall progress 0-100 weighted across phases."""
        phase_weights = {
            "discovery": 0.10,
            "metadata": 0.15,
            "commit_analysis": 0.60,
            "indexing": 0.15,
        }
        phase_idx = self.PHASES.index(self.current_phase) if self.current_phase in self.PHASES else 0
        completed_phases_weight = sum(
            phase_weights.get(p, 0) for p in self.PHASES[:phase_idx]
        )
        current_weight = phase_weights.get(self.current_phase, 0)

        if self.current_phase == "discovery":
            inner = 0.5  # unknown total during discovery
        elif self.current_phase == "metadata" and self.total_projects > 0:
            inner = self.projects_processed / self.total_projects
        elif self.current_phase == "commit_analysis" and self.total_commits > 0:
            inner = self.commits_processed / self.total_commits
        elif self.current_phase == "indexing" and self.total_files > 0:
            inner = self.files_processed / self.total_files
        else:
            inner = 0.0

        return min(99, int((completed_phases_weight + current_weight * inner) * 100))

    def as_dict(self) -> dict:
        elapsed = self.elapsed()
        commit_rate = self.commits_processed / elapsed if elapsed > 0 else 0
        return {
            "phase": self.current_phase,
            "progress_percent": self.progress_percent(),
            "current_project": self.current_project,
            "current_operation": self.current_operation,
            "projects_total": self.total_projects,
            "projects_processed": self.projects_processed,
            "commits_total": self.total_commits,
            "commits_processed": self.commits_processed,
            "commits_skipped_duplicate": self.commits_skipped_duplicate,
            "commits_skipped_old": self.commits_skipped_old,
            "files_total": self.total_files,
            "files_processed": self.files_processed,
            "elapsed_seconds": round(elapsed, 1),
            "commit_rate": round(commit_rate, 1),
            "ai_calls_made": self.ai_calls_made,
            "ai_cost_usd": round(self.ai_cost_usd, 6),
        }

    # ------------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------------

    async def emit(self, force: bool = False) -> None:
        """Fire the progress callback if the interval has elapsed."""
        if self.progress_callback is None:
            return
        now = time.time()
        if not force and (now - self._last_callback_time) < self._callback_interval:
            return
        self._last_callback_time = now
        await self.progress_callback(self.as_dict())

    def print_progress(self) -> None:
        """Print a compact progress line to stdout (CLI mode)."""
        d = self.as_dict()
        print(
            f"\r  [{d['phase']:16s}]  projects {d['projects_processed']}/{d['projects_total']}"
            f"  commits {d['commits_processed']}/{d['commits_total']}"
            f"  {d['progress_percent']:3d}%"
            f"  {d['elapsed_seconds']:.0f}s"
            f"  current: {(d['current_project'] or '')[:30]}",
            end="",
            flush=True,
        )
