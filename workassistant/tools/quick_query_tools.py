"""
Lightweight query tools for instant answers without triggering full scans.
Tier 1: Instant queries (filesystem-based, no git operations)
"""
import os
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import select, func
from workassistant.database import async_session_maker
from workassistant.models.project import Project
from workassistant.models.project_location import ProjectLocation
from workassistant.config import SCAN_IGNORE_PATTERNS


def _is_git_repo(path: Path) -> bool:
    """Quick check if a directory is a git repository."""
    return (path / '.git').exists()


def _should_ignore(path: Path) -> bool:
    """Check if path should be ignored based on patterns."""
    name = path.name
    for pattern in SCAN_IGNORE_PATTERNS:
        if pattern.startswith('*'):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


async def count_repos_at_location(location_path: str, max_depth: int = 3) -> Dict:
    """
    Quickly count git repositories at a location without scanning metadata.
    
    Args:
        location_path: Path to search for repositories
        max_depth: Maximum directory depth to search (default: 3)
        
    Returns:
        Dictionary with count and list of repo paths
    """
    location_path = Path(location_path).expanduser().resolve()
    
    if not location_path.exists():
        return {"error": f"Location does not exist: {location_path}"}
    
    if not location_path.is_dir():
        return {"error": f"Not a directory: {location_path}"}
    
    repos = []
    
    def scan_directory(path: Path, depth: int = 0):
        """Recursively scan for git repos."""
        if depth > max_depth:
            return
        
        try:
            if _is_git_repo(path):
                repos.append(str(path))
                return  # Don't scan inside git repos
            
            # Scan subdirectories
            for item in path.iterdir():
                if item.is_dir() and not _should_ignore(item):
                    scan_directory(item, depth + 1)
        except (PermissionError, OSError):
            pass  # Skip inaccessible directories
    
    scan_directory(location_path)
    
    return {
        "success": True,
        "location": str(location_path),
        "count": len(repos),
        "repositories": repos,
        "max_depth": max_depth
    }


async def list_repos_fast(location_path: str, max_depth: int = 3) -> Dict:
    """
    Quickly list git repositories with basic info (name only, no git metadata).
    
    Args:
        location_path: Path to search for repositories
        max_depth: Maximum directory depth to search
        
    Returns:
        Dictionary with list of repositories
    """
    result = await count_repos_at_location(location_path, max_depth)
    
    if "error" in result:
        return result
    
    repos_info = [
        {
            "name": Path(repo).name,
            "path": repo,
            "type": "git"
        }
        for repo in result["repositories"]
    ]
    
    return {
        "success": True,
        "location": str(location_path),
        "count": len(repos_info),
        "repositories": repos_info
    }


async def check_if_repo(path: str) -> Dict:
    """
    Check if a specific path is a git repository.
    
    Args:
        path: Path to check
        
    Returns:
        Dictionary with result
    """
    path = Path(path).expanduser().resolve()
    
    if not path.exists():
        return {
            "success": True,
            "path": str(path),
            "exists": False,
            "is_git_repo": False
        }
    
    is_git = _is_git_repo(path)
    
    return {
        "success": True,
        "path": str(path),
        "exists": True,
        "is_directory": path.is_dir(),
        "is_git_repo": is_git,
        "name": path.name if path.is_dir() else None
    }


async def get_cached_project_stats(location_path: Optional[str] = None) -> Dict:
    """
    Get project statistics from database cache (instant, no filesystem access).
    
    Args:
        location_path: Optional path to filter by location
        
    Returns:
        Dictionary with cached statistics
    """
    async with async_session_maker() as session:
        query = select(Project).where(Project.is_active == True)
        
        if location_path:
            # Find location_id for the path
            location_path = str(Path(location_path).expanduser().resolve())
            loc_result = await session.execute(
                select(ProjectLocation).where(ProjectLocation.path == location_path)
            )
            location = loc_result.scalar_one_or_none()
            
            if not location:
                return {
                    "error": f"Location not found in database: {location_path}",
                    "hint": "Run scan_projects() first to index this location"
                }
            
            query = query.where(Project.location_id == location.id)
        
        # Get counts by type
        result = await session.execute(query)
        projects = result.scalars().all()
        
        git_repos = [p for p in projects if p.project_type == "git"]
        plain_folders = [p for p in projects if p.project_type == "plain"]
        
        # Language breakdown
        languages = {}
        for p in projects:
            if p.language:
                languages[p.language] = languages.get(p.language, 0) + 1
        
        return {
            "success": True,
            "location": location_path if location_path else "all locations",
            "total_projects": len(projects),
            "git_repositories": len(git_repos),
            "plain_folders": len(plain_folders),
            "languages": languages,
            "last_scanned": max([p.last_scanned_at for p in projects if p.last_scanned_at], default=None),
            "cached": True,
            "hint": "This data is from the database. Run scan_projects() to update."
        }


async def search_projects_by_name(name_pattern: str) -> Dict:
    """
    Search for projects by name pattern (instant database query).
    
    Args:
        name_pattern: Name pattern to search for (case-insensitive)
        
    Returns:
        Dictionary with matching projects
    """
    async with async_session_maker() as session:
        query = select(Project).where(
            Project.is_active == True,
            Project.name.ilike(f"%{name_pattern}%")
        ).order_by(Project.name)
        
        result = await session.execute(query)
        projects = result.scalars().all()
        
        return {
            "success": True,
            "pattern": name_pattern,
            "count": len(projects),
            "projects": [
                {
                    "name": p.name,
                    "path": p.path,
                    "type": p.project_type,
                    "language": p.language,
                    "last_scanned": p.last_scanned_at.isoformat() if p.last_scanned_at else None
                }
                for p in projects
            ]
        }


async def get_project_locations() -> Dict:
    """
    List all configured project locations (instant database query).
    
    Returns:
        Dictionary with locations
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProjectLocation).where(ProjectLocation.is_active == True)
        )
        locations = result.scalars().all()
        
        return {
            "success": True,
            "count": len(locations),
            "locations": [
                {
                    "id": loc.id,
                    "path": loc.path,
                    "is_primary": loc.is_primary,
                    "last_scanned": loc.last_scanned_at.isoformat() if loc.last_scanned_at else None
                }
                for loc in locations
            ]
        }
