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

async def scan_projects(location_path: str) -> Dict[str, any]:
    """
    Scan a location for projects (git repos and plain folders).
    Detects .git folders for git repos, extracts metadata.
    
    Args:
        location_path: Path to scan for projects
        
    Returns:
        Dictionary with scan results including number of projects found
    """
    location_path = Path(location_path).expanduser().resolve()
    
    if not location_path.exists():
        return {"error": f"Location does not exist: {location_path}"}
    
    projects_found = []
    
    async with async_session_maker() as session:
        location = await session.execute(
            select(ProjectLocation).where(ProjectLocation.path == str(location_path))
        )
        location_record = location.scalar_one_or_none()
        
        if not location_record:
            location_record = ProjectLocation(
                path=str(location_path),
                is_primary=False,
                is_active=True
            )
            session.add(location_record)
            await session.commit()
            await session.refresh(location_record)
        
        for item in location_path.iterdir():
            if not item.is_dir():
                continue
                
            if item.name.startswith('.'):
                continue
            
            project_data = await _extract_project_metadata(item, location_record.id)
            
            if project_data:
                existing = await session.execute(
                    select(Project).where(Project.path == str(item))
                )
                existing_project = existing.scalar_one_or_none()
                
                if existing_project:
                    for key, value in project_data.items():
                        setattr(existing_project, key, value)
                    existing_project.last_scanned_at = datetime.utcnow()
                else:
                    project = Project(**project_data, last_scanned_at=datetime.utcnow())
                    session.add(project)
                
                projects_found.append(project_data['name'])
        
        await session.commit()
    
    return {
        "success": True,
        "location": str(location_path),
        "projects_found": len(projects_found),
        "projects": projects_found
    }

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
