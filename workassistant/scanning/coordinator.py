import asyncio
from typing import List, Callable, Awaitable

from workassistant.database import async_session_maker
from workassistant.config import SCAN_WORKERS


class ParallelScanCoordinator:
    """Distributes projects across async workers and collects results."""

    def __init__(self, num_workers: int = SCAN_WORKERS):
        self.num_workers = num_workers

    def distribute(self, projects: list) -> dict[int, list]:
        """Sort projects smallest-first (by commit_count), round-robin assign
        to workers.  Returns {worker_id: [project_path, ...]}."""
        sorted_projects = sorted(
            projects,
            key=lambda p: p.get("commit_count") or 0,
        )
        assignments: dict[int, list] = {i: [] for i in range(self.num_workers)}
        for idx, project in enumerate(sorted_projects):
            assignments[idx % self.num_workers].append(project)
        return assignments

    async def run(
        self,
        projects: list,
        worker_fn: Callable[[int, list], Awaitable[dict]],
    ) -> List[dict]:
        """Run worker_fn concurrently for each worker bucket.

        worker_fn(worker_id, project_list) -> result dict
        Returns list of result dicts from all workers.
        """
        assignments = self.distribute(projects)
        tasks = [
            asyncio.create_task(worker_fn(worker_id, project_list))
            for worker_id, project_list in assignments.items()
            if project_list
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out exceptions; they are logged inside worker_fn
        return [r for r in results if isinstance(r, dict)]
