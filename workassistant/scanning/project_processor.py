"""
Single project processor for hierarchical job system.
Processes one project through metadata → commits → indexing phases.
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable, Optional, Dict

logger = logging.getLogger(__name__)

import git
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.database import async_session_maker
from workassistant.models.project import Project
from workassistant.models.commit_summary import CommitSummary
from workassistant.models.file_index import FileIndex
from workassistant.scanning.commit_summarizer import CommitSummaryGenerator
from workassistant.scanning.journal_generator import JournalAutoGenerator
from workassistant.scanning.git_helpers import get_commit_diff_sync, get_file_stats_sync
from workassistant.config import MAX_FILE_SIZE_BYTES, SCAN_IGNORE_PATTERNS


ProgressCallback = Callable[[dict], Awaitable[None]]


async def process_single_project(
    project_path: Path,
    project_type: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict:
    """
    Process a single project through all scan phases.
    
    Args:
        project_path: Path to the project
        project_type: 'git' or 'plain'
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dictionary with processing results
    """
    result = {
        "project_path": str(project_path),
        "project_type": project_type,
        "commits_analyzed": 0,
        "commits_skipped": 0,
        "files_indexed": 0,
        "journal_entries_created": 0,
        "ai_calls": 0,
        "ai_cost_usd": 0.0,
        "errors": [],
    }
    
    async def emit_progress(phase: str, progress_percent: int, **kwargs):
        if progress_callback:
            await progress_callback({
                "phase": phase,
                "progress_percent": progress_percent,
                **kwargs
            })
    
    try:
        async with async_session_maker() as session:
            # Phase 1: Metadata
            await emit_progress("metadata", 10)
            project_record = await _process_metadata(session, project_path, project_type)
            
            if not project_record:
                result["errors"].append("Failed to create project record")
                return result
            
            # Phase 2: Commits (only for git repos)
            if project_type == "git":
                await emit_progress("commits", 30)
                commit_result = await _process_commits(
                    session, project_record, project_path, emit_progress
                )
                result.update(commit_result)
            
            # Phase 3: Indexing
            await emit_progress("indexing", 70)
            index_result = await _process_indexing(
                session, project_record, project_path, emit_progress
            )
            result["files_indexed"] = index_result.get("files_indexed", 0)
            
            await emit_progress("done", 100)
            
    except Exception as exc:
        logger.error(f"Error processing project {project_path}: {exc}", exc_info=True)
        result["errors"].append(str(exc))
        raise
    
    return result


async def _process_metadata(
    session: AsyncSession,
    project_path: Path,
    project_type: str,
) -> Optional[Project]:
    """Extract and save project metadata."""
    try:
        # Check if project already exists
        result = await session.execute(
            select(Project).where(Project.path == str(project_path))
        )
        project = result.scalar_one_or_none()
        
        metadata = {
            "name": project_path.name,
            "path": str(project_path),
            "project_type": project_type,
            "is_active": True,
            "last_scanned_at": datetime.now(timezone.utc),
        }
        
        # Extract git metadata if applicable
        if project_type == "git":
            git_metadata = await _extract_git_metadata(project_path)
            metadata.update(git_metadata)
        
        # Detect language
        language = _detect_language(project_path)
        if language:
            metadata["language"] = language
        
        if project:
            # Update existing
            for key, value in metadata.items():
                setattr(project, key, value)
        else:
            # Create new
            project = Project(**metadata)
            session.add(project)
        
        await session.commit()
        await session.refresh(project)
        
        return project
        
    except Exception as exc:
        logger.error(f"Failed to process metadata for {project_path}: {exc}")
        return None


async def _extract_git_metadata(project_path: Path) -> Dict:
    """Extract git-specific metadata."""
    metadata = {}
    
    try:
        repo = git.Repo(project_path)
        
        if not repo.bare:
            try:
                metadata["current_branch"] = repo.active_branch.name
            except:
                pass
            
            try:
                last_commit = repo.head.commit
                metadata["last_commit_sha"] = last_commit.hexsha
                metadata["last_commit_message"] = last_commit.message.strip()
                metadata["last_commit_date"] = datetime.fromtimestamp(
                    last_commit.committed_date, tz=timezone.utc
                )
            except:
                pass
    except:
        pass
    
    return metadata


def _detect_language(project_path: Path) -> Optional[str]:
    """Detect primary programming language."""
    language_files = {
        'Python': ['setup.py', 'pyproject.toml', 'requirements.txt'],
        'JavaScript': ['package.json'],
        'TypeScript': ['tsconfig.json'],
        'Rust': ['Cargo.toml'],
        'Go': ['go.mod'],
        'Java': ['pom.xml', 'build.gradle'],
        'Ruby': ['Gemfile'],
        'PHP': ['composer.json'],
    }
    
    for lang, files in language_files.items():
        for file in files:
            if (project_path / file).exists():
                return lang
    
    return None


async def _process_commits(
    session: AsyncSession,
    project: Project,
    project_path: Path,
    emit_progress: Callable,
) -> Dict:
    """Process git commits with AI summarization."""
    result = {
        "commits_analyzed": 0,
        "commits_skipped": 0,
        "ai_calls": 0,
        "ai_cost_usd": 0.0,
    }
    
    try:
        repo = git.Repo(project_path)
        
        if repo.bare:
            return result
        
        # Get commits to process
        commits = list(repo.iter_commits(max_count=100))  # Limit for now
        total_commits = len(commits)
        
        summarizer = CommitSummaryGenerator()
        
        for idx, commit in enumerate(commits):
            # Check if already processed
            existing = await session.execute(
                select(CommitSummary).where(
                    CommitSummary.project_id == project.id,
                    CommitSummary.commit_sha == commit.hexsha
                )
            )
            if existing.scalar_one_or_none():
                result["commits_skipped"] += 1
                continue
            
            # Generate summary
            try:
                diff = get_commit_diff_sync(repo, commit.hexsha)
                summary_result = await summarizer.generate_summary(
                    commit_sha=commit.hexsha,
                    commit_message=commit.message,
                    diff_text=diff,
                    project_id=project.id,
                )
                
                if summary_result:
                    result["commits_analyzed"] += 1
                    result["ai_calls"] += summary_result.get("ai_calls", 0)
                    result["ai_cost_usd"] += summary_result.get("cost_usd", 0.0)
                
            except Exception as exc:
                logger.warning(f"Failed to summarize commit {commit.hexsha}: {exc}")
            
            # Update progress
            progress = int(30 + (idx / total_commits) * 40)  # 30-70%
            await emit_progress("commits", progress, commits_processed=idx + 1, commits_total=total_commits)
        
        await session.commit()
        
    except Exception as exc:
        logger.error(f"Failed to process commits for {project_path}: {exc}")
    
    return result


async def _process_indexing(
    session: AsyncSession,
    project: Project,
    project_path: Path,
    emit_progress: Callable,
) -> Dict:
    """Index project files."""
    result = {
        "files_indexed": 0,
    }
    
    try:
        files_to_index = []
        
        # Walk project directory
        for item in project_path.rglob('*'):
            if item.is_file() and not _should_ignore(item):
                if item.stat().st_size <= MAX_FILE_SIZE_BYTES:
                    files_to_index.append(item)
        
        total_files = len(files_to_index)
        
        for idx, file_path in enumerate(files_to_index):
            try:
                # Check if already indexed
                existing = await session.execute(
                    select(FileIndex).where(
                        FileIndex.project_id == project.id,
                        FileIndex.file_path == str(file_path.relative_to(project_path))
                    )
                )
                
                if not existing.scalar_one_or_none():
                    # Create file index entry
                    file_index = FileIndex(
                        project_id=project.id,
                        file_path=str(file_path.relative_to(project_path)),
                        file_type=file_path.suffix.lstrip('.') if file_path.suffix else 'unknown',
                        file_size=file_path.stat().st_size,
                        indexed_at=datetime.now(timezone.utc),
                    )
                    session.add(file_index)
                    result["files_indexed"] += 1
                
            except Exception as exc:
                logger.warning(f"Failed to index file {file_path}: {exc}")
            
            # Update progress
            if total_files > 0:
                progress = int(70 + (idx / total_files) * 30)  # 70-100%
                await emit_progress("indexing", progress, files_processed=idx + 1, files_total=total_files)
        
        await session.commit()
        
    except Exception as exc:
        logger.error(f"Failed to index files for {project_path}: {exc}")
    
    return result


def _should_ignore(path: Path) -> bool:
    """Check if path should be ignored."""
    parts = path.parts
    for part in parts:
        if part.startswith('.'):
            return True
        if any(pat.strip() and part == pat.strip() for pat in SCAN_IGNORE_PATTERNS):
            return True
    return False
