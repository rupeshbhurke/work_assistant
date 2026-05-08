"""
Synchronous Git helper functions for use with asyncio.to_thread().
These functions perform blocking Git operations that should be run in a thread pool.
"""
import logging
from pathlib import Path
import git

logger = logging.getLogger(__name__)


def get_commit_diff_sync(project_path: str, commit_sha: str) -> str:
    """Get the diff for a specific commit."""
    try:
        repo = git.Repo(project_path)
        commit = repo.commit(commit_sha)
        if commit.parents:
            diff = repo.git.diff(commit.parents[0].hexsha, commit.hexsha)
        else:
            diff = repo.git.show(commit.hexsha, "--format=")
        return diff
    except Exception as e:
        logger.error(f"Error getting diff for commit {commit_sha}: {e}")
        return ""


def get_file_stats_sync(project_path: str, commit_sha: str) -> dict:
    """Get file change statistics for a commit."""
    result = {
        "added": 0,
        "modified": 0,
        "deleted": 0,
        "files": []
    }
    try:
        repo = git.Repo(project_path)
        commit = repo.commit(commit_sha)
        
        if commit.parents:
            diff_obj = commit.parents[0].diff(commit)
        else:
            diff_obj = commit.diff(None)
            
        for d in diff_obj:
            if d.new_file:
                result["added"] += 1
                result["files"].append(d.b_path)
            elif d.deleted_file:
                result["deleted"] += 1
                result["files"].append(d.a_path)
            else:
                result["modified"] += 1
                result["files"].append(d.a_path)
                
    except Exception as e:
        logger.error(f"Error getting file stats for commit {commit_sha}: {e}")
        
    return result
