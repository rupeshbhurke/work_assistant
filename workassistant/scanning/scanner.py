"""
Multi-phase project scanner.
Phases: discovery → metadata → commit_analysis → indexing
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)

import git
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.database import async_session_maker
from workassistant.models.project import Project
from workassistant.models.project_location import ProjectLocation
from workassistant.models.commit_summary import CommitSummary
from workassistant.models.file_index import FileIndex
from workassistant.scanning.checkpoint_manager import ScanCheckpointManager
from workassistant.scanning.change_detector import ChangeDetector
from workassistant.scanning.progress_tracker import ScanProgressTracker
from workassistant.scanning.commit_summarizer import CommitSummaryGenerator
from workassistant.scanning.journal_generator import JournalAutoGenerator
from workassistant.scanning.coordinator import ParallelScanCoordinator
from workassistant.scanning.git_helpers import get_commit_diff_sync, get_file_stats_sync
from workassistant.config import (
    SCAN_WORKERS,
    MAX_FILE_SIZE_BYTES,
    SCAN_IGNORE_PATTERNS,
)


ProgressCallback = Callable[[dict], Awaitable[None]]


class ProjectScanner:
    """Orchestrates all four scan phases for a project location."""

    def __init__(
        self,
        location_id: int,
        worker_id: int = 0,
        progress_callback: Optional[ProgressCallback] = None,
        dry_run: bool = False,
        incremental: bool = True,
    ):
        self.location_id = location_id
        self.worker_id = worker_id
        self.progress_callback = progress_callback
        self.dry_run = dry_run
        self.incremental = incremental

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def run(self) -> dict:
        """Execute all phases and return a summary dict."""
        async with async_session_maker() as session:
            checkpoint = ScanCheckpointManager(session, self.location_id, self.worker_id)
            resumed = await checkpoint.load()

            tracker = ScanProgressTracker(progress_callback=self.progress_callback)

            result = {
                "location_id": self.location_id,
                "resumed": resumed,
                "projects_found": 0,
                "projects_processed": 0,
                "commits_analyzed": 0,
                "commits_skipped_dup": 0,
                "commits_skipped_old": 0,
                "files_indexed": 0,
                "journal_entries_created": 0,
                "ai_calls": 0,
                "ai_cost_usd": 0.0,
                "errors": [],
            }

            try:
                logger.info(f"Starting scan for location_id={self.location_id}, worker_id={self.worker_id}, incremental={self.incremental}")
                # Phase 1 – Discovery
                projects = await self._phase_discovery(session, checkpoint, tracker, resumed)
                result["projects_found"] = len(projects)
                logger.info(f"Discovery phase found {len(projects)} projects")

                if not projects:
                    await checkpoint.complete()
                    logger.info("No projects found, scan complete")
                    return result

                # Phase 2-4 – Process via parallel workers
                coordinator = ParallelScanCoordinator(num_workers=SCAN_WORKERS)

                async def worker(worker_id: int, project_list: list) -> dict:
                    return await self._process_projects(
                        project_list, worker_id, tracker
                    )

                worker_results = await coordinator.run(projects, worker)

                for wr in worker_results:
                    result["projects_processed"] += wr.get("projects_processed", 0)
                    result["commits_analyzed"] += wr.get("commits_analyzed", 0)
                    result["commits_skipped_dup"] += wr.get("commits_skipped_dup", 0)
                    result["commits_skipped_old"] += wr.get("commits_skipped_old", 0)
                    result["files_indexed"] += wr.get("files_indexed", 0)
                    result["journal_entries_created"] += wr.get("journal_entries_created", 0)
                    result["ai_calls"] += wr.get("ai_calls", 0)
                    result["ai_cost_usd"] += wr.get("ai_cost_usd", 0.0)
                    result["errors"].extend(wr.get("errors", []))

                await checkpoint.complete()
                tracker.set_phase("indexing")
                await tracker.emit(force=True)
                logger.info(f"Scan completed: {result}")
            except asyncio.CancelledError:
                logger.warning("Scan cancelled")
                await checkpoint.save(force=True)
                raise
            except Exception as exc:
                result["errors"].append(str(exc))
                logger.error(f"Scan error: {exc}", exc_info=True)
                raise

            return result

    # ------------------------------------------------------------------
    # Phase 1: Discovery
    # ------------------------------------------------------------------

    async def _phase_discovery(
        self,
        session: AsyncSession,
        checkpoint: ScanCheckpointManager,
        tracker: ScanProgressTracker,
        resumed: bool,
    ) -> list:
        tracker.set_phase("discovery")
        await tracker.emit()

        # Fetch location path
        loc_result = await session.execute(
            select(ProjectLocation).where(ProjectLocation.id == self.location_id)
        )
        location = loc_result.scalar_one_or_none()
        if not location:
            return []

        root = Path(location.path).expanduser().resolve()
        if not root.exists():
            return []

        if resumed and checkpoint.projects_found:
            # Restore from checkpoint
            return checkpoint.projects_found

        # Walk the tree finding git repos and plain folders
        discovered: list = []
        for item in self._walk_directories(root):
            if checkpoint.is_project_processed(str(item)):
                continue
            git_dir = item / ".git"
            is_git = git_dir.exists()
            entry = {
                "path": str(item),
                "name": item.name,
                "project_type": "git" if is_git else "plain",
                "commit_count": 0,
            }
            if is_git:
                entry["commit_count"] = await self._estimate_commit_count(item)
            discovered.append(entry)
            checkpoint.mark_project_found(entry)  # Pass full dict, not just path
            await checkpoint.save()
            await tracker.emit()

        tracker.set_totals(projects=len(discovered))
        return discovered

    def _walk_directories(self, root: Path):
        """Yield all direct-child and nested directories that look like
        projects (have a .git dir, or have no sub-directories that are
        themselves projects).  Skips ignored patterns at every level."""
        try:
            entries = [e for e in root.iterdir() if e.is_dir() and not e.is_symlink()]
        except (PermissionError, OSError):
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if any(pat.strip() and entry.name == pat.strip() for pat in SCAN_IGNORE_PATTERNS):
                continue

            if (entry / ".git").exists():
                yield entry
            else:
                # Check if this is a leaf project-like directory
                has_sub_git = any(
                    (sub / ".git").exists()
                    for sub in entry.iterdir()
                    if sub.is_dir() and not sub.name.startswith(".")
                ) if entry.is_dir() else False

                if has_sub_git:
                    # Recurse: containers like a workspace folder
                    yield from self._walk_directories(entry)
                else:
                    # Plain folder project
                    yield entry

    @staticmethod
    def _estimate_commit_count_sync(repo_path: Path) -> int:
        """Synchronous helper for commit count estimation."""
        try:
            repo = git.Repo(repo_path)
            return sum(1 for _ in repo.iter_commits(max_count=500))
        except Exception:
            return 0
    
    async def _estimate_commit_count(self, repo_path: Path) -> int:
        """Async wrapper with timeout for commit count estimation."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._estimate_commit_count_sync, repo_path),
                timeout=30.0  # 30 second timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Timeout estimating commits for {repo_path}")
            return 0
        except Exception as e:
            logger.error(f"Error estimating commits for {repo_path}: {e}")
            return 0

    # ------------------------------------------------------------------
    # Phases 2-4 (per-worker)
    # ------------------------------------------------------------------

    async def _process_projects(
        self,
        project_list: list,
        worker_id: int,
        tracker: ScanProgressTracker,
    ) -> dict:
        result = {
            "projects_processed": 0,
            "commits_analyzed": 0,
            "commits_skipped_dup": 0,
            "commits_skipped_old": 0,
            "files_indexed": 0,
            "journal_entries_created": 0,
            "ai_calls": 0,
            "ai_cost_usd": 0.0,
            "errors": [],
        }

        async with async_session_maker() as session:
            checkpoint = ScanCheckpointManager(session, self.location_id, worker_id)
            await checkpoint.load()
            summarizer = CommitSummaryGenerator(session)
            detector = ChangeDetector(session)
            journal_gen = JournalAutoGenerator(session)

            for project_info in project_list:
                if checkpoint.is_project_processed(project_info["path"]):
                    result["projects_processed"] += 1
                    tracker.increment_projects()
                    continue

                tracker.set_current_project(project_info["name"], "metadata")
                await tracker.emit()

                try:
                    # Wrap entire project processing in timeout (5 minutes max per project)
                    await asyncio.wait_for(
                        self._process_single_project(
                            session, project_info, checkpoint, tracker, 
                            summarizer, detector, journal_gen, result
                        ),
                        timeout=300.0  # 5 minute timeout per project
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Project {project_info['name']} timed out after 5 minutes, skipping")
                    result["errors"].append(f"{project_info['name']}: Processing timeout (5 min)")
                    checkpoint.mark_project_processed(project_info["path"])
                    await checkpoint.save(force=True)
                except asyncio.CancelledError:
                    await checkpoint.save(force=True)
                    raise
                except Exception as exc:
                    result["errors"].append(f"{project_info['name']}: {exc}")

        return result

    async def _process_single_project(
        self,
        session: AsyncSession,
        project_info: dict,
        checkpoint: ScanCheckpointManager,
        tracker: ScanProgressTracker,
        summarizer: CommitSummaryGenerator,
        detector: ChangeDetector,
        journal_gen: JournalAutoGenerator,
        result: dict,
    ) -> None:
        """Process a single project with all phases."""
        try:
            # Phase 2 – Metadata
            project = await self._upsert_project(session, project_info)
            checkpoint.set_current_project(project_info["path"], "metadata")
            await checkpoint.save()

            if project_info["project_type"] == "git" and not self.dry_run:
                # Phase 3 – Commit analysis
                tracker.set_current_project(project_info["name"], "commit_analysis")
                tracker.set_phase("commit_analysis")
                await tracker.emit()
                ca = await self._phase_commit_analysis(
                    session, project, checkpoint, tracker, summarizer
                )
                result["commits_analyzed"] += ca["analyzed"]
                result["commits_skipped_dup"] += ca["skipped_dup"]
                result["commits_skipped_old"] += ca["skipped_old"]
                result["ai_calls"] += ca["ai_calls"]
                result["ai_cost_usd"] += ca["ai_cost_usd"]

                # Auto-generate journal entries
                created = await journal_gen.generate_for_project(project.id)
                result["journal_entries_created"] += created

            if not self.dry_run:
                # Phase 4 – File indexing
                tracker.set_current_project(project_info["name"], "indexing")
                tracker.set_phase("indexing")
                await tracker.emit()
                files_count = await self._phase_file_indexing(
                    session, project, checkpoint, tracker, detector
                )
                result["files_indexed"] += files_count

            checkpoint.mark_project_processed(project_info["path"])
            await checkpoint.save(force=True)
            result["projects_processed"] += 1
            tracker.increment_projects()
            tracker.set_phase("commit_analysis")
            await tracker.emit()

        except asyncio.CancelledError:
            await checkpoint.save(force=True)
            raise
        except Exception as exc:
            result["errors"].append(f"{project_info['name']}: {exc}")

        return result

    # ------------------------------------------------------------------
    # Phase 2: Metadata upsert
    # ------------------------------------------------------------------

    async def _upsert_project(self, session: AsyncSession, project_info: dict) -> Project:
        path = project_info["path"]
        result = await session.execute(select(Project).where(Project.path == path))
        project = result.scalar_one_or_none()

        meta = await self._extract_metadata(Path(path), self.location_id)

        if project:
            for k, v in meta.items():
                setattr(project, k, v)
            project.last_scanned_at = datetime.now(timezone.utc)
        else:
            project = Project(**meta, last_scanned_at=datetime.now(timezone.utc))
            session.add(project)

        await session.flush()
        await session.commit()
        await session.refresh(project)
        return project

    @staticmethod
    def _extract_git_metadata_sync(project_path: Path) -> dict:
        """Synchronous Git metadata extraction."""
        meta = {}
        try:
            repo = git.Repo(project_path)
            if not repo.bare:
                try:
                    meta["current_branch"] = repo.active_branch.name
                except Exception:
                    meta["current_branch"] = "detached"
                try:
                    lc = repo.head.commit
                    meta["last_commit_hash"] = lc.hexsha
                    meta["last_commit_message"] = lc.message.strip()
                    meta["last_commit_date"] = datetime.fromtimestamp(
                        lc.committed_date, tz=timezone.utc
                    )
                    meta["commit_count"] = sum(1 for _ in repo.iter_commits(max_count=10000))
                except Exception:
                    pass
        except Exception:
            pass
        return meta

    async def _extract_metadata(self, project_path: Path, location_id: int) -> dict:
        git_dir = project_path / ".git"
        is_git = git_dir.exists()
        meta = {
            "name": project_path.name,
            "path": str(project_path),
            "project_type": "git" if is_git else "plain",
            "location_id": location_id,
            "is_active": True,
        }

        if is_git:
            try:
                git_meta = await asyncio.wait_for(
                    asyncio.to_thread(self._extract_git_metadata_sync, project_path),
                    timeout=30.0
                )
                meta.update(git_meta)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout extracting Git metadata for {project_path}")
            except Exception as e:
                logger.error(f"Error extracting Git metadata for {project_path}: {e}")

        # README description
        for readme in ("README.md", "readme.md", "README.txt"):
            rp = project_path / readme
            if rp.exists():
                try:
                    with open(rp, "r", encoding="utf-8", errors="ignore") as f:
                        first_line = f.read(500).split("\n")[0][:200]
                    meta["description"] = first_line
                except Exception:
                    pass
                break

        # Language detection
        lang_files = {
            "package.json": "JavaScript/TypeScript",
            "requirements.txt": "Python",
            "setup.py": "Python",
            "pyproject.toml": "Python",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "pom.xml": "Java",
            "build.gradle": "Java",
            "Gemfile": "Ruby",
            "composer.json": "PHP",
        }
        for fname, lang in lang_files.items():
            if (project_path / fname).exists():
                meta["language"] = lang
                break

        return meta

    # ------------------------------------------------------------------
    # Phase 3: Commit analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _get_new_commits_sync(project_path: str, resume_sha: str) -> list:
        """Synchronous helper to get new commits."""
        try:
            repo = git.Repo(project_path)
            new_commits = []
            for commit in repo.iter_commits():
                if resume_sha and commit.hexsha == resume_sha:
                    break
                new_commits.append(commit)
            return new_commits
        except Exception as e:
            logger.error(f"Error getting commits for {project_path}: {e}")
            return []

    async def _phase_commit_analysis(
        self,
        session: AsyncSession,
        project: Project,
        checkpoint: ScanCheckpointManager,
        tracker: ScanProgressTracker,
        summarizer: CommitSummaryGenerator,
    ) -> dict:
        result = {
            "analyzed": 0,
            "skipped_dup": 0,
            "skipped_old": 0,
            "ai_calls": 0,
            "ai_cost_usd": 0.0,
        }

        # Get new commits with timeout
        try:
            new_commits = await asyncio.wait_for(
                asyncio.to_thread(
                    self._get_new_commits_sync,
                    project.path,
                    project.last_analyzed_commit_hash
                ),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"Timeout getting commits for {project.path}")
            return result
        except Exception as e:
            logger.error(f"Error in commit analysis for {project.path}: {e}")
            return result

        if not new_commits:
            return result

        tracker.set_totals(commits=tracker.total_commits + len(new_commits))

        for commit in reversed(new_commits):  # oldest-first
            sha = commit.hexsha

            # Deduplication check
            if await checkpoint.is_commit_analyzed(sha):
                await checkpoint.register_commit(sha, project.id)
                result["skipped_dup"] += 1
                tracker.increment_commits(skipped_dup=True)
                await tracker.emit()
                continue

            # Check if summary already saved for this project
            existing = await session.execute(
                select(CommitSummary).where(
                    CommitSummary.project_id == project.id,
                    CommitSummary.commit_hash == sha,
                )
            )
            if existing.scalar_one_or_none() is not None:
                await checkpoint.register_commit(sha, project.id)
                tracker.increment_commits()
                await tracker.emit()
                continue

            checkpoint.set_current_commit(sha)
            await checkpoint.save()

            # Build diff string with timeout
            try:
                diff_str = await asyncio.wait_for(
                    asyncio.to_thread(get_commit_diff_sync, project.path, commit.hexsha),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting diff for commit {commit.hexsha}")
                diff_str = ""
            commit_date = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc)
            commit_meta = {
                "hash": sha,
                "author": str(commit.author),
                "date": commit_date.isoformat(),
                "message": commit.message.strip(),
            }

            # Generate AI summary
            summary_result = await summarizer.generate_summary(diff_str, commit_meta)

            if summary_result.get("ai_skipped") and "older than" in (summary_result.get("ai_error") or ""):
                result["skipped_old"] += 1
                tracker.increment_commits(skipped_old=True)
            else:
                if summary_result.get("api_call_id"):
                    result["ai_calls"] += 1
                    # Approximate cost from tracker
                tracker.increment_commits()

            # Count changed files with timeout
            files_added = files_modified = files_deleted = 0
            changed_file_list = []
            try:
                file_stats = await asyncio.wait_for(
                    asyncio.to_thread(get_file_stats_sync, project.path, commit.hexsha),
                    timeout=30.0
                )
                files_added = file_stats.get("added", 0)
                files_modified = file_stats.get("modified", 0)
                files_deleted = file_stats.get("deleted", 0)
                changed_file_list = file_stats.get("files", [])
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting file stats for commit {commit.hexsha}")
            except Exception:
                pass

            cs = CommitSummary(
                project_id=project.id,
                commit_hash=sha,
                author=str(commit.author),
                commit_date=commit_date,
                commit_message=commit.message.strip(),
                summary=summary_result.get("summary"),
                files_changed=changed_file_list[:100],  # cap at 100
                files_added=files_added,
                files_modified=files_modified,
                files_deleted=files_deleted,
                diff_size=len(diff_str.encode()),
                language=project.language,
                ai_skipped=summary_result.get("ai_skipped", False),
                ai_error=summary_result.get("ai_error"),
                ai_api_call_id=summary_result.get("api_call_id"),
            )
            session.add(cs)
            await checkpoint.register_commit(sha, project.id)
            result["analyzed"] += 1

            # Update project's last analyzed pointer
            await session.execute(
                update(Project)
                .where(Project.id == project.id)
                .values(
                    last_analyzed_commit_hash=sha,
                    last_analyzed_commit_date=commit_date,
                )
            )
            await session.commit()
            await tracker.emit()

        return result

    @staticmethod
    def _get_commit_diff(repo: git.Repo, commit) -> str:
        try:
            if commit.parents:
                diff = repo.git.diff(commit.parents[0].hexsha, commit.hexsha)
            else:
                diff = repo.git.show(commit.hexsha, "--format=")
            return diff
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Phase 4: File indexing
    # ------------------------------------------------------------------

    async def _phase_file_indexing(
        self,
        session: AsyncSession,
        project: Project,
        checkpoint: ScanCheckpointManager,
        tracker: ScanProgressTracker,
        detector: ChangeDetector,
    ) -> int:
        changes = await detector.detect_changes(project)
        if not changes["has_changes"]:
            return 0

        count = 0
        now = datetime.now(timezone.utc)

        # Handle modified / added files
        for rel_path, file_hash in changes["current_files"].items():
            if rel_path in changes["added"] or rel_path in changes["modified"]:
                abs_path = Path(project.path) / rel_path
                try:
                    stat = abs_path.stat()
                    file_size = stat.st_size
                    last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                except (OSError, PermissionError):
                    continue

                # Skip files exceeding size limit
                if file_size > MAX_FILE_SIZE_BYTES:
                    continue

                # Upsert file index
                existing_result = await session.execute(
                    select(FileIndex).where(
                        FileIndex.project_id == project.id,
                        FileIndex.file_path == rel_path,
                    )
                )
                existing = existing_result.scalar_one_or_none()

                if existing:
                    existing.file_hash = file_hash
                    existing.file_size = file_size
                    existing.last_modified = last_modified
                    existing.is_deleted = False
                    existing.updated_at = now
                else:
                    session.add(FileIndex(
                        project_id=project.id,
                        file_path=rel_path,
                        file_hash=file_hash,
                        file_size=file_size,
                        last_modified=last_modified,
                        language=project.language,
                        is_binary=False,
                        is_deleted=False,
                    ))
                count += 1
                tracker.increment_files()
                checkpoint.set_current_file(rel_path)
                await checkpoint.save()
                await tracker.emit()

        # Soft-delete removed files
        for rel_path in changes["deleted"]:
            result = await session.execute(
                select(FileIndex).where(
                    FileIndex.project_id == project.id,
                    FileIndex.file_path == rel_path,
                )
            )
            fi = result.scalar_one_or_none()
            if fi:
                fi.is_deleted = True
                fi.updated_at = now

        await session.commit()
        return count
