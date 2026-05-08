import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import git
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from workassistant.models.project import Project
from workassistant.models.project_location import ProjectLocation
from workassistant.database import async_session_maker
from workassistant.jobs.scan_job_manager import scan_job_manager


async def scan_projects(location_path: str, incremental: bool = True) -> Dict[str, any]:
    """
    Start a background scan of a location for projects (git repos and plain folders).
    The scan runs asynchronously. Returns a job_id to track progress.

    Args:
        location_path: Path to scan for projects
        incremental: Only process projects/commits that changed since last scan

    Returns:
        Dictionary with job_id and status — use check_scan_status(job_id) to poll progress
    """
    location_path = Path(location_path).expanduser().resolve()

    if not location_path.exists():
        return {"error": f"Location does not exist: {location_path}"}

    # Ensure the ProjectLocation record exists
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProjectLocation).where(ProjectLocation.path == str(location_path))
        )
        location_record = result.scalar_one_or_none()

        if not location_record:
            location_record = ProjectLocation(
                path=str(location_path),
                is_primary=False,
                is_active=True,
            )
            session.add(location_record)
            await session.commit()
            await session.refresh(location_record)

        location_id = location_record.id

    job_id = await scan_job_manager.start_scan(
        location_id=location_id,
        incremental=incremental,
    )

    return {
        "success": True,
        "job_id": job_id,
        "status": "started",
        "location": str(location_path),
        "message": (
            f"Scan started in background. "
            f"job_id: {job_id}. "
            f"Use check_scan_status('{job_id}') to monitor progress."
        ),
    }


async def check_scan_status(job_id: str) -> Dict[str, any]:
    """
    Check the status and progress of a background scan job.

    Args:
        job_id: The job ID returned by scan_projects

    Returns:
        Dictionary with current status, phase, progress percentage, and metrics
    """
    return await scan_job_manager.get_status(job_id)

async def _extract_project_metadata(project_path: Path, location_id: int) -> Optional[Dict]:
    """Extract metadata from a project directory."""
    git_dir = project_path / '.git'
    is_git = git_dir.exists()
    
    metadata = {
        "name": project_path.name,
        "path": str(project_path),
        "project_type": "git" if is_git else "plain",
        "location_id": location_id,
        "is_active": True,
    }
    
    if is_git:
        try:
            repo = git.Repo(project_path)
            
            if not repo.bare:
                try:
                    metadata["current_branch"] = repo.active_branch.name
                except:
                    metadata["current_branch"] = "detached"
                
                try:
                    last_commit = repo.head.commit
                    metadata["last_commit_hash"] = last_commit.hexsha
                    metadata["last_commit_message"] = last_commit.message.strip()
                    metadata["last_commit_date"] = datetime.fromtimestamp(last_commit.committed_date)
                except:
                    pass
        except Exception as e:
            pass
    
    readme_path = project_path / 'README.md'
    if not readme_path.exists():
        readme_path = project_path / 'readme.md'
    if not readme_path.exists():
        readme_path = project_path / 'README.txt'
    
    if readme_path.exists():
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                content = f.read(500)
                metadata["description"] = content.split('\n')[0][:200]
        except:
            pass
    
    common_languages = {
        'package.json': 'JavaScript/TypeScript',
        'requirements.txt': 'Python',
        'setup.py': 'Python',
        'pyproject.toml': 'Python',
        'Cargo.toml': 'Rust',
        'go.mod': 'Go',
        'pom.xml': 'Java',
        'build.gradle': 'Java',
        'Gemfile': 'Ruby',
        'composer.json': 'PHP',
    }
    
    for file, lang in common_languages.items():
        if (project_path / file).exists():
            metadata["language"] = lang
            break
    
    return metadata

async def list_projects(filter_type: Optional[str] = None, active_only: bool = True) -> List[Dict]:
    """
    List all tracked projects.
    
    Args:
        filter_type: Filter by project type ('git' or 'plain'), None for all
        active_only: Only return active projects
        
    Returns:
        List of project dictionaries
    """
    async with async_session_maker() as session:
        query = select(Project)
        
        if active_only:
            query = query.where(Project.is_active == True)
        
        if filter_type:
            query = query.where(Project.project_type == filter_type)
        
        query = query.order_by(Project.name)
        
        result = await session.execute(query)
        projects = result.scalars().all()
        
        return [
            {
                "id": p.id,
                "name": p.name,
                "path": p.path,
                "type": p.project_type,
                "language": p.language,
                "description": p.description,
                "current_branch": p.current_branch,
                "last_commit": p.last_commit_message,
                "last_scanned": p.last_scanned_at.isoformat() if p.last_scanned_at else None,
            }
            for p in projects
        ]

async def add_project_location(path: str, is_primary: bool = False) -> Dict:
    """
    Add a new project location to scan.
    
    Args:
        path: Path to the project location
        is_primary: Whether this is a primary location
        
    Returns:
        Dictionary with result
    """
    path = str(Path(path).expanduser().resolve())
    
    if not Path(path).exists():
        return {"error": f"Path does not exist: {path}"}
    
    async with async_session_maker() as session:
        existing = await session.execute(
            select(ProjectLocation).where(ProjectLocation.path == path)
        )
        
        if existing.scalar_one_or_none():
            return {"error": f"Location already exists: {path}"}
        
        location = ProjectLocation(
            path=path,
            is_primary=is_primary,
            is_active=True
        )
        session.add(location)
        await session.commit()
        
        return {
            "success": True,
            "message": f"Added project location: {path}",
            "is_primary": is_primary
        }

async def git_log(project_name: str, limit: int = 10) -> Dict:
    """
    Get recent git commits for a project.
    
    Args:
        project_name: Name of the project
        limit: Number of commits to retrieve
        
    Returns:
        Dictionary with commit history
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Project).where(Project.name == project_name)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            return {"error": f"Project not found: {project_name}"}
        
        if project.project_type != "git":
            return {"error": f"Project '{project_name}' is not a git repository"}
        
        try:
            repo = git.Repo(project.path)
            commits = []
            
            for commit in repo.iter_commits(max_count=limit):
                commits.append({
                    "hash": commit.hexsha[:8],
                    "author": str(commit.author),
                    "date": datetime.fromtimestamp(commit.committed_date).isoformat(),
                    "message": commit.message.strip(),
                })
            
            return {
                "success": True,
                "project": project_name,
                "branch": project.current_branch,
                "commits": commits
            }
        except Exception as e:
            return {"error": f"Failed to read git log: {str(e)}"}

async def git_diff_summary(project_name: str, commit_hash: Optional[str] = None) -> Dict:
    """
    Get a summary of changes in a commit or recent changes.
    
    Args:
        project_name: Name of the project
        commit_hash: Specific commit hash, or None for recent changes
        
    Returns:
        Dictionary with diff summary
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Project).where(Project.name == project_name)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            return {"error": f"Project not found: {project_name}"}
        
        if project.project_type != "git":
            return {"error": f"Project '{project_name}' is not a git repository"}
        
        try:
            repo = git.Repo(project.path)
            
            if commit_hash:
                commit = repo.commit(commit_hash)
                if commit.parents:
                    diff = commit.parents[0].diff(commit)
                else:
                    diff = commit.diff(None)
            else:
                diff = repo.head.commit.diff('HEAD~1')
            
            changes = {
                "added": [],
                "modified": [],
                "deleted": [],
                "renamed": []
            }
            
            for change in diff:
                if change.new_file:
                    changes["added"].append(change.b_path)
                elif change.deleted_file:
                    changes["deleted"].append(change.a_path)
                elif change.renamed_file:
                    changes["renamed"].append(f"{change.a_path} -> {change.b_path}")
                else:
                    changes["modified"].append(change.a_path)
            
            return {
                "success": True,
                "project": project_name,
                "commit": commit_hash or "HEAD",
                "changes": changes,
                "total_files": sum(len(v) for v in changes.values())
            }
        except Exception as e:
            return {"error": f"Failed to get diff: {str(e)}"}
