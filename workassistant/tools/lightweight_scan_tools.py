"""
Tier 2: Lightweight scan tools - basic git metadata without deep analysis.
Fast queries with minimal git operations, no AI, no indexing.
"""
import git
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
from workassistant.tools.quick_query_tools import _is_git_repo, _should_ignore


async def get_repo_basic_info(repo_path: str) -> Dict:
    """
    Get basic git repository information without deep scanning.
    
    Args:
        repo_path: Path to the git repository
        
    Returns:
        Dictionary with basic repo info
    """
    repo_path = Path(repo_path).expanduser().resolve()
    
    if not repo_path.exists():
        return {"error": f"Path does not exist: {repo_path}"}
    
    if not _is_git_repo(repo_path):
        return {"error": f"Not a git repository: {repo_path}"}
    
    try:
        repo = git.Repo(repo_path)
        
        # Get basic info
        info = {
            "success": True,
            "name": repo_path.name,
            "path": str(repo_path),
            "is_bare": repo.bare,
        }
        
        if not repo.bare:
            # Current branch
            try:
                info["current_branch"] = repo.active_branch.name
            except:
                info["current_branch"] = None
            
            # Last commit
            try:
                last_commit = repo.head.commit
                info["last_commit"] = {
                    "sha": last_commit.hexsha[:8],
                    "message": last_commit.message.strip().split('\n')[0],
                    "author": str(last_commit.author),
                    "date": datetime.fromtimestamp(last_commit.committed_date, tz=timezone.utc).isoformat()
                }
            except:
                info["last_commit"] = None
            
            # Branch count
            try:
                info["branch_count"] = len(list(repo.branches))
            except:
                info["branch_count"] = 0
            
            # Remote info
            try:
                remotes = list(repo.remotes)
                info["remotes"] = [{"name": r.name, "url": list(r.urls)[0] if r.urls else None} for r in remotes]
            except:
                info["remotes"] = []
        
        return info
        
    except Exception as e:
        return {"error": f"Failed to read repository: {str(e)}"}


async def get_repo_commit_count(repo_path: str, branch: Optional[str] = None, since_days: Optional[int] = None) -> Dict:
    """
    Get commit count for a repository without analyzing commits.
    
    Args:
        repo_path: Path to the git repository
        branch: Specific branch to check (default: current branch)
        since_days: Only count commits from last N days
        
    Returns:
        Dictionary with commit count
    """
    repo_path = Path(repo_path).expanduser().resolve()
    
    if not repo_path.exists():
        return {"error": f"Path does not exist: {repo_path}"}
    
    if not _is_git_repo(repo_path):
        return {"error": f"Not a git repository: {repo_path}"}
    
    try:
        repo = git.Repo(repo_path)
        
        if repo.bare:
            return {"error": "Cannot count commits in bare repository"}
        
        # Determine branch
        if branch:
            try:
                commit_iter = repo.iter_commits(branch)
            except:
                return {"error": f"Branch not found: {branch}"}
        else:
            try:
                commit_iter = repo.iter_commits(repo.active_branch)
                branch = repo.active_branch.name
            except:
                return {"error": "No active branch"}
        
        # Count commits
        if since_days:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
            count = sum(1 for c in commit_iter if datetime.fromtimestamp(c.committed_date, tz=timezone.utc) >= cutoff)
        else:
            count = sum(1 for _ in commit_iter)
        
        return {
            "success": True,
            "path": str(repo_path),
            "branch": branch,
            "commit_count": count,
            "since_days": since_days
        }
        
    except Exception as e:
        return {"error": f"Failed to count commits: {str(e)}"}


async def get_repos_with_recent_activity(location_path: str, days: int = 7, max_depth: int = 3) -> Dict:
    """
    Find repositories with recent commits (lightweight scan).
    
    Args:
        location_path: Path to search for repositories
        days: Number of days to look back
        max_depth: Maximum directory depth to search
        
    Returns:
        Dictionary with active repositories
    """
    from workassistant.tools.quick_query_tools import count_repos_at_location
    from datetime import timedelta
    
    # First get all repos
    repos_result = await count_repos_at_location(location_path, max_depth)
    
    if "error" in repos_result:
        return repos_result
    
    active_repos = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    for repo_path in repos_result["repositories"]:
        try:
            repo = git.Repo(repo_path)
            if not repo.bare:
                try:
                    last_commit = repo.head.commit
                    commit_date = datetime.fromtimestamp(last_commit.committed_date, tz=timezone.utc)
                    
                    if commit_date >= cutoff:
                        active_repos.append({
                            "name": Path(repo_path).name,
                            "path": repo_path,
                            "last_commit_date": commit_date.isoformat(),
                            "last_commit_message": last_commit.message.strip().split('\n')[0],
                            "branch": repo.active_branch.name
                        })
                except:
                    pass
        except:
            pass
    
    # Sort by most recent first
    active_repos.sort(key=lambda x: x["last_commit_date"], reverse=True)
    
    return {
        "success": True,
        "location": str(location_path),
        "days": days,
        "total_repos_scanned": repos_result["count"],
        "active_repos_count": len(active_repos),
        "active_repositories": active_repos
    }


async def detect_repo_language(repo_path: str) -> Dict:
    """
    Detect primary language of a repository by checking common files.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        Dictionary with detected language
    """
    repo_path = Path(repo_path).expanduser().resolve()
    
    if not repo_path.exists():
        return {"error": f"Path does not exist: {repo_path}"}
    
    # Language detection patterns
    language_files = {
        'Python': ['setup.py', 'pyproject.toml', 'requirements.txt', 'Pipfile'],
        'JavaScript': ['package.json', 'yarn.lock'],
        'TypeScript': ['tsconfig.json'],
        'Rust': ['Cargo.toml'],
        'Go': ['go.mod', 'go.sum'],
        'Java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
        'Ruby': ['Gemfile', 'Rakefile'],
        'PHP': ['composer.json'],
        'C++': ['CMakeLists.txt', 'Makefile'],
        'C#': ['.csproj', '.sln'],
        'Swift': ['Package.swift'],
    }
    
    detected = []
    
    for lang, files in language_files.items():
        for file in files:
            if (repo_path / file).exists():
                detected.append(lang)
                break
    
    # Count file extensions as fallback
    if not detected:
        extension_count = {}
        try:
            for item in repo_path.rglob('*'):
                if item.is_file() and not _should_ignore(item.parent):
                    ext = item.suffix.lower()
                    if ext:
                        extension_count[ext] = extension_count.get(ext, 0) + 1
        except:
            pass
        
        # Map extensions to languages
        ext_to_lang = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.rs': 'Rust',
            '.go': 'Go',
            '.java': 'Java',
            '.rb': 'Ruby',
            '.php': 'PHP',
            '.cpp': 'C++',
            '.c': 'C',
            '.cs': 'C#',
            '.swift': 'Swift',
        }
        
        if extension_count:
            most_common_ext = max(extension_count, key=extension_count.get)
            if most_common_ext in ext_to_lang:
                detected.append(ext_to_lang[most_common_ext])
    
    return {
        "success": True,
        "path": str(repo_path),
        "languages": detected,
        "primary_language": detected[0] if detected else "Unknown"
    }


async def compare_repo_sizes(location_path: str, max_depth: int = 3) -> Dict:
    """
    Compare repository sizes at a location (by commit count, not disk size).
    
    Args:
        location_path: Path to search for repositories
        max_depth: Maximum directory depth to search
        
    Returns:
        Dictionary with repository sizes
    """
    from workassistant.tools.quick_query_tools import count_repos_at_location
    
    repos_result = await count_repos_at_location(location_path, max_depth)
    
    if "error" in repos_result:
        return repos_result
    
    repo_sizes = []
    
    for repo_path in repos_result["repositories"]:
        try:
            repo = git.Repo(repo_path)
            if not repo.bare:
                try:
                    commit_count = sum(1 for _ in repo.iter_commits(repo.active_branch))
                    repo_sizes.append({
                        "name": Path(repo_path).name,
                        "path": repo_path,
                        "commit_count": commit_count,
                        "branch": repo.active_branch.name
                    })
                except:
                    pass
        except:
            pass
    
    # Sort by commit count
    repo_sizes.sort(key=lambda x: x["commit_count"], reverse=True)
    
    return {
        "success": True,
        "location": str(location_path),
        "total_repos": len(repo_sizes),
        "repositories": repo_sizes,
        "largest": repo_sizes[0] if repo_sizes else None,
        "smallest": repo_sizes[-1] if repo_sizes else None
    }
