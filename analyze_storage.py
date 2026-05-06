#!/usr/bin/env python
"""
Analyze Git repositories to estimate database storage requirements.
This script scans all projects and calculates the storage needed to store
commit history, file metadata, and other information in the database.
"""
import os
import git
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import sys
import time
from threading import Thread, Event
import json

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from workassistant.config import PRIMARY_PROJECT_ROOT, ADDITIONAL_PROJECT_ROOTS

CHECKPOINT_FILE = "storage_analysis_checkpoint.json"

class CheckpointManager:
    """Manage checkpoints for resuming analysis."""
    
    def __init__(self, checkpoint_file: str = CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        self.last_save_time = time.time()
        self.data = {
            'phase': 'quick_scan',
            'quick_scan_complete': False,
            'git_repos_found': [],
            'analyzed_repos': [],
            'non_git_projects': [],
            'timestamp': None,
            'total_commits': 0,
            'current_repo': None,  # Currently analyzing repo path
            'current_repo_commit': 0,  # Commit count in current repo
            'current_repo_partial_stats': None,  # Partial stats for current repo
            'analyzed_commit_shas': {},  # SHA -> first repo that analyzed it (for deduplication)
            'unique_commits': 0,  # Count of unique commits across all repos
            'duplicate_commits': 0  # Count of duplicate commits found
        }
        self.load()
    
    def load(self):
        """Load checkpoint if exists."""
        if Path(self.checkpoint_file).exists():
            try:
                with open(self.checkpoint_file, 'r') as f:
                    self.data = json.load(f)
                print(f"📂 Loaded checkpoint from {self.checkpoint_file}", flush=True)
                print(f"   Phase: {self.data.get('phase', 'quick_scan')}", flush=True)
                print(f"   Quick scan complete: {self.data.get('quick_scan_complete', False)}", flush=True)
                print(f"   Repos found: {len(self.data.get('git_repos_found', []))}", flush=True)
                print(f"   Repos analyzed: {len(self.data.get('analyzed_repos', []))}", flush=True)
                if self.data.get('current_repo'):
                    print(f"   Current repo: {self.data.get('current_repo')} (commit {self.data.get('current_repo_commit', 0)})", flush=True)
                print(flush=True)
            except Exception as e:
                print(f"⚠️  Failed to load checkpoint: {e}", flush=True)
                self.data = {
                    'phase': 'quick_scan',
                    'quick_scan_complete': False,
                    'git_repos_found': [],
                    'analyzed_repos': [],
                    'non_git_projects': [],
                    'timestamp': None,
                    'total_commits': 0,
                    'current_repo': None,
                    'current_repo_commit': 0,
                    'current_repo_partial_stats': None,
                    'analyzed_commit_shas': {},
                    'unique_commits': 0,
                    'duplicate_commits': 0
                }
                self.last_save_time = time.time()
    
    def save(self):
        """Save current checkpoint."""
        self.data['timestamp'] = datetime.now().isoformat()
        try:
            with open(self.checkpoint_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            self.last_save_time = time.time()
        except Exception as e:
            print(f"⚠️  Failed to save checkpoint: {e}", flush=True)
    
    def should_save_by_time(self) -> bool:
        """Check if 2 minutes have passed since last save."""
        return (time.time() - self.last_save_time) >= 120  # 2 minutes
    
    def save_quick_scan(self, git_repos: list, total_commits: int):
        """Save quick scan results (final)."""
        self.data['phase'] = 'detailed_analysis'
        self.data['quick_scan_complete'] = True
        # Only update if not already set (incremental adds may have already populated)
        if not self.data['git_repos_found']:
            self.data['git_repos_found'] = git_repos
            self.data['total_commits'] = total_commits
        self.save()
    
    def complete_quick_scan(self):
        """Mark quick scan as complete."""
        self.data['phase'] = 'detailed_analysis'
        self.data['quick_scan_complete'] = True
        self.save()
    
    def save_repo_analysis(self, repo_stats: dict):
        """Save a single repo analysis result."""
        # Check if already analyzed
        for i, repo in enumerate(self.data['analyzed_repos']):
            if repo.get('path') == repo_stats.get('path'):
                self.data['analyzed_repos'][i] = repo_stats
                self.save()
                return
        
        self.data['analyzed_repos'].append(repo_stats)
        self.save()
    
    def save_non_git_project(self, path: str):
        """Save a non-git project."""
        if path not in self.data['non_git_projects']:
            self.data['non_git_projects'].append(path)
            self.save()
    
    def get_analyzed_paths(self) -> set:
        """Get set of already analyzed repo paths."""
        return {repo['path'] for repo in self.data['analyzed_repos']}
    
    def get_found_repos(self) -> list:
        """Get list of repos found in quick scan."""
        return self.data['git_repos_found']
    
    def is_quick_scan_complete(self) -> bool:
        """Check if quick scan is complete."""
        return self.data['quick_scan_complete']
    
    def add_found_repo(self, repo_info: dict):
        """Add a single found repo during quick scan (incremental)."""
        # Check if already exists
        for existing in self.data['git_repos_found']:
            if existing['path'] == repo_info['path']:
                return
        
        self.data['git_repos_found'].append(repo_info)
        self.data['total_commits'] = sum(r['commit_count'] for r in self.data['git_repos_found'])
        
        # Save every 5 repos or every 2 minutes
        if len(self.data['git_repos_found']) % 5 == 0 or self.should_save_by_time():
            self.save()
    
    def get_found_repo_paths(self) -> set:
        """Get set of already found repo paths."""
        return {repo['path'] for repo in self.data['git_repos_found']}
    
    def clear(self):
        """Clear checkpoint."""
        if Path(self.checkpoint_file).exists():
            Path(self.checkpoint_file).unlink()
        self.data = {
            'phase': 'quick_scan',
            'quick_scan_complete': False,
            'git_repos_found': [],
            'analyzed_repos': [],
            'non_git_projects': [],
            'timestamp': None,
            'total_commits': 0,
            'current_repo': None,
            'current_repo_commit': 0,
            'current_repo_partial_stats': None,
            'analyzed_commit_shas': {},
            'unique_commits': 0,
            'duplicate_commits': 0
        }
        self.last_save_time = time.time()
    
    def set_current_repo(self, repo_path: str, commit_count: int = 0, partial_stats: dict = None):
        """Set the currently analyzing repo."""
        self.data['current_repo'] = repo_path
        self.data['current_repo_commit'] = commit_count
        self.data['current_repo_partial_stats'] = partial_stats
        self.save()
    
    def update_current_repo_progress(self, commit_count: int, partial_stats: dict):
        """Update commit count and partial stats for current repo."""
        self.data['current_repo_commit'] = commit_count
        self.data['current_repo_partial_stats'] = partial_stats
        # Only save if time-based or every 20 commits
        if self.should_save_by_time() or commit_count % 20 == 0:
            self.save()
    
    def clear_current_repo(self):
        """Clear current repo (when analysis completes)."""
        self.data['current_repo'] = None
        self.data['current_repo_commit'] = 0
        self.data['current_repo_partial_stats'] = None
        self.save()
    
    def get_current_repo(self) -> tuple:
        """Get current repo path, commit count, and partial stats."""
        return (
            self.data.get('current_repo'),
            self.data.get('current_repo_commit', 0),
            self.data.get('current_repo_partial_stats')
        )


class ProgressTracker:
    """Track and display progress with periodic updates."""
    
    def __init__(self, total_repos: int, total_commits: int = 0):
        self.total_repos = total_repos
        self.analyzed_repos = 0
        self.total_commits = total_commits
        self.analyzed_commits = 0
        self.start_time = time.time()
        self.last_update = 0
        self.stop_event = Event()
        self.current_repo_name = None
        
    def increment_analyzed(self, commit_count: int = 0):
        """Increment analyzed repo count and optionally commit count."""
        self.analyzed_repos += 1
        self.analyzed_commits += commit_count
        
    def update_commits(self, commit_count: int):
        """Update analyzed commits count."""
        self.analyzed_commits = commit_count
    
    def set_current_repo(self, repo_name: str):
        """Set the name of the currently analyzing repo."""
        self.current_repo_name = repo_name
    
    def clear_current_repo(self):
        """Clear current repo name."""
        self.current_repo_name = None
        
    def start_updater(self):
        """Start background thread for periodic updates."""
        def update_loop():
            while not self.stop_event.is_set():
                time.sleep(2)  # Update every 2 seconds
                self.display_progress()
        
        self.thread = Thread(target=update_loop, daemon=True)
        self.thread.start()
        
    def stop_updater(self):
        """Stop the background updater."""
        self.stop_event.set()
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1)
        self.display_progress(final=True)
        
    def display_progress(self, final=False):
        """Display current progress."""
        elapsed = time.time() - self.start_time
        
        if self.total_repos > 0:
            repo_progress = (self.analyzed_repos / self.total_repos) * 100
        else:
            repo_progress = 0
        
        if self.total_commits > 0:
            commit_progress = (self.analyzed_commits / self.total_commits) * 100
            # Calculate ETA based on commits (more accurate)
            if self.analyzed_commits > 0:
                remaining_commits = self.total_commits - self.analyzed_commits
                remaining = (elapsed / self.analyzed_commits) * remaining_commits
                # Calculate processing rate
                rate = self.analyzed_commits / elapsed if elapsed > 0 else 0
            else:
                remaining = 0
                rate = 0
        else:
            commit_progress = 0
            remaining = 0
            rate = 0
        
        progress_str = f"\r  ⏳  Progress: {self.analyzed_repos}/{self.total_repos} repos ({repo_progress:.1f}%)"
        
        if self.total_commits > 0:
            progress_str += f" | {self.analyzed_commits:,}/{self.total_commits:,} commits ({commit_progress:.1f}%)"
        
        # Add processing rate
        if rate > 0:
            progress_str += f" | Rate: {rate:.0f} commits/s"
        
        # Add current repo name
        if self.current_repo_name:
            progress_str += f" | Current: {self.current_repo_name}"
        
        progress_str += f" | Elapsed: {elapsed:.1f}s"
        
        if remaining > 0:
            progress_str += f" | ETA: {remaining:.1f}s"
        
        print(progress_str, end='' if not final else '\n', flush=True)

def quick_scan_estimate(path: Path, checkpoint=None, max_depth: int = 10) -> dict:
    """Quick scan to find git repos and estimate their commit counts.
    Returns list of git repos with estimated commit counts.
    
    Args:
        path: Path to scan
        checkpoint: Optional checkpoint manager for incremental saving
        max_depth: Maximum recursion depth
    """
    git_repos = []
    last_report = 0
    start_time = time.time()
    
    # Get already found repos if resuming
    already_found = set()
    if checkpoint:
        already_found = checkpoint.get_found_repo_paths()
        git_repos = checkpoint.get_found_repos().copy()
        print(f"    Resuming: {len(git_repos)} repos already found", flush=True)
    
    def find_git_repos(p: Path, depth: int = 0):
        nonlocal git_repos, last_report
        if depth > max_depth:
            return
        
        try:
            for item in p.iterdir():
                if not item.is_dir():
                    continue
                
                if item.name in ['node_modules', '.venv', 'venv', '__pycache__', 'target', 'build', 'dist', '.git']:
                    continue
                
                git_dir = item / '.git'
                item_path = str(item)
                
                if git_dir.exists():
                    # Check if already found and if it has new commits
                    existing_repo = None
                    if item_path in already_found:
                        for repo in git_repos:
                            if repo['path'] == item_path:
                                existing_repo = repo
                                break
                    
                    # Quick estimate of commit count and latest commit date
                    try:
                        repo = git.Repo(item)
                        
                        # Get latest commit date
                        latest_commit = next(repo.iter_commits(max_count=1))
                        latest_commit_date = datetime.fromtimestamp(latest_commit.committed_date).isoformat()
                        
                        # Check if repo has new commits
                        if existing_repo:
                            existing_date = existing_repo.get('last_commit_date', '')
                            if latest_commit_date <= existing_date:
                                # No new commits, skip
                                print(f"    Skipping: {item.name} (no new commits since {existing_date[:10]})", flush=True)
                                continue
                            else:
                                # Has new commits, recount
                                print(f"    Updating: {item.name} (new commits detected)", flush=True)
                        
                        commit_count = sum(1 for _ in repo.iter_commits(max_count=10000))
                        repo_info = {
                            'path': item_path,
                            'name': item.name,
                            'commit_count': commit_count,
                            'last_commit_date': latest_commit_date
                        }
                        
                        # Update or add to list
                        if existing_repo:
                            # Update existing entry
                            for i, r in enumerate(git_repos):
                                if r['path'] == item_path:
                                    git_repos[i] = repo_info
                                    break
                        else:
                            git_repos.append(repo_info)
                            print(f"    Found: {item.name} (~{commit_count} commits)", flush=True)
                        
                        # Save to checkpoint incrementally
                        if checkpoint:
                            checkpoint.add_found_repo(repo_info)
                    except:
                        repo_info = {
                            'path': item_path,
                            'name': item.name,
                            'commit_count': 0,
                            'last_commit_date': None
                        }
                        
                        if not existing_repo:
                            git_repos.append(repo_info)
                            print(f"    Found: {item.name} (error counting)", flush=True)
                            
                            # Save to checkpoint incrementally
                            if checkpoint:
                                checkpoint.add_found_repo(repo_info)
                else:
                    find_git_repos(item, depth + 1)
                    
                    # Report progress every 5 repos
                    if len(git_repos) - last_report >= 5:
                        elapsed = time.time() - start_time
                        print(f"    Scanning... {len(git_repos)} git repos found so far ({elapsed:.1f}s)", flush=True)
                        last_report = len(git_repos)
        except:
            pass
    
    find_git_repos(path)
    return {
        'git_repos': git_repos,
        'total_repos': len(git_repos),
        'total_commits': sum(r['commit_count'] for r in git_repos)
    }

def analyze_git_repo(repo_path: Path, progress_callback=None, checkpoint=None, resume_from_commit=0, partial_stats=None, last_analyzed_date=None) -> dict:
    """Analyze a single Git repository and calculate storage requirements.
    
    Args:
        repo_path: Path to the git repository
        progress_callback: Optional callback function(current_commit, total_estimated) for progress updates
        checkpoint: Optional checkpoint manager for saving progress mid-analysis
        resume_from_commit: Commit number to resume from (for checkpoint resume)
        partial_stats: Partial stats to resume from (if resuming mid-analysis)
        last_analyzed_date: Timestamp of last analysis (only process commits after this)
    """
    try:
        repo = git.Repo(repo_path)
        
        # Get latest commit date for smart updates
        latest_commit_date = None
        try:
            latest_commit = next(repo.iter_commits(max_count=1))
            latest_commit_date = datetime.fromtimestamp(latest_commit.committed_date).isoformat()
        except:
            pass
        
        # Get global analyzed commit SHAs for deduplication
        analyzed_shas = checkpoint.data.get('analyzed_commit_shas', {}) if checkpoint else {}
        new_commits = 0
        duplicate_commits = 0
        
        # Initialize or resume from partial stats
        if partial_stats:
            stats = partial_stats.copy()
            authors = set(stats.get('authors_list', []))
            commit_count = resume_from_commit
            total_message_size = stats.get('total_commit_message_size', 0)
            total_file_changes = stats.get('total_file_changes', 0)
            largest_commit = stats.get('largest_commit', 0)
            file_types = defaultdict(int, stats.get('file_types', {}))
        else:
            stats = {
                'name': repo_path.name,
                'path': str(repo_path),
                'is_bare': repo.bare,
                'num_commits': 0,
                'num_branches': 0,
                'num_authors': 0,
                'total_commit_message_size': 0,
                'total_file_changes': 0,
                'avg_commit_message_size': 0,
                'commits_by_author': defaultdict(int),
                'file_types': defaultdict(int),
                'largest_commit': 0,
            }
            authors = set()
            commit_count = 0
            total_message_size = 0
            total_file_changes = 0
            largest_commit = 0
            file_types = defaultdict(int)
        
        last_progress_update = resume_from_commit
        
        try:
            for commit in repo.iter_commits():
                commit_count += 1
                
                # Skip commits if resuming from checkpoint
                if commit_count <= resume_from_commit:
                    continue
                
                # Skip commits already analyzed (based on date)
                if last_analyzed_date:
                    commit_date = datetime.fromtimestamp(commit.committed_date)
                    analyzed_date = datetime.fromisoformat(last_analyzed_date)
                    if commit_date <= analyzed_date:
                        # All remaining commits are older, stop processing
                        break
                
                # Check if this commit was already analyzed in another repo (deduplication)
                commit_sha = commit.hexsha
                if commit_sha in analyzed_shas:
                    duplicate_commits += 1
                    # Skip detailed analysis but count the commit
                    continue
                else:
                    new_commits += 1
                    # Mark this commit as analyzed
                    if checkpoint:
                        analyzed_shas[commit_sha] = str(repo_path)
                
                authors.add(str(commit.author))
                total_message_size += len(commit.message.encode('utf-8'))
                
                # Count file changes in this commit
                try:
                    if commit.parents:
                        diff = commit.parents[0].diff(commit)
                        file_changes = len(diff)
                        total_file_changes += file_changes
                        if file_changes > largest_commit:
                            largest_commit = file_changes
                            
                        # Track file types
                        for diff_item in diff:
                            if diff_item.a_path:
                                ext = Path(diff_item.a_path).suffix
                                if ext:
                                    file_types[ext] += 1
                except:
                    pass
                
                # Update progress every 20 commits (changed from 100)
                if progress_callback and commit_count - last_progress_update >= 20:
                    progress_callback(commit_count)
                    last_progress_update = commit_count
                    
                    # Save checkpoint progress with partial stats
                    if checkpoint:
                        current_partial_stats = {
                            'name': repo_path.name,
                            'path': str(repo_path),
                            'is_bare': repo.bare,
                            'num_commits': commit_count,
                            'num_authors': len(authors),
                            'total_commit_message_size': total_message_size,
                            'total_file_changes': total_file_changes,
                            'largest_commit': largest_commit,
                            'file_types': dict(file_types),
                            'authors_list': list(authors)  # For resume
                        }
                        checkpoint.update_current_repo_progress(commit_count, current_partial_stats)
                
                # Limit to 10000 commits for very large repos to avoid long analysis
                if commit_count >= 10000:
                    print(f"  ⚠️  Limiting analysis to 10,000 commits for {repo_path.name}", flush=True)
                    break
        except Exception as e:
            print(f"  ⚠️  Error iterating commits: {e}", flush=True)
        
        # Count branches
        try:
            stats['num_branches'] = len(list(repo.branches))
        except:
            pass
        
        # Calculate final statistics
        stats['num_commits'] = commit_count
        stats['num_commits_unique'] = new_commits  # New unique commits in this repo
        stats['num_commits_duplicate'] = duplicate_commits  # Commits already seen in other repos
        stats['num_authors'] = len(authors)
        stats['total_commit_message_size'] = total_message_size
        stats['total_file_changes'] = total_file_changes
        stats['largest_commit'] = largest_commit
        stats['avg_commit_message_size'] = total_message_size / new_commits if new_commits > 0 else 0
        stats['commits_by_author'] = dict(stats.get('commits_by_author', {}))
        stats['file_types'] = dict(file_types)
        stats['last_commit_date'] = latest_commit_date
        stats['last_analyzed_date'] = datetime.now().isoformat()
        
        # Update global deduplication stats
        if checkpoint:
            checkpoint.data['analyzed_commit_shas'] = analyzed_shas
            checkpoint.data['unique_commits'] = len(analyzed_shas)
            checkpoint.data['duplicate_commits'] = checkpoint.data.get('duplicate_commits', 0) + duplicate_commits
        
        # Remove temporary fields used for resume
        stats.pop('authors_list', None)
        
        return stats
        
    except Exception as e:
        return {
            'name': repo_path.name,
            'path': str(repo_path),
            'error': str(e)
        }

def estimate_db_storage(repo_stats: list) -> dict:
    """Estimate database storage requirements based on repository analysis."""
    
    total_commits = sum(r.get('num_commits', 0) for r in repo_stats)
    total_message_size = sum(r.get('total_commit_message_size', 0) for r in repo_stats)
    total_file_changes = sum(r.get('total_file_changes', 0) for r in repo_stats)
    
    # Database storage estimates (per row)
    # These are conservative estimates for PostgreSQL with indexes
    commit_record_size = 500  # bytes per commit record (including overhead)
    author_record_size = 200  # bytes per author
    file_change_record_size = 300  # bytes per file change
    project_record_size = 1000  # bytes per project metadata
    
    # Calculate storage
    commits_storage = total_commits * commit_record_size
    messages_storage = total_message_size
    file_changes_storage = total_file_changes * file_change_record_size
    projects_storage = len(repo_stats) * project_record_size
    
    # Index overhead (approx 30% of data size)
    index_overhead = (commits_storage + messages_storage + file_changes_storage) * 0.3
    
    total_storage = (
        commits_storage +
        messages_storage +
        file_changes_storage +
        projects_storage +
        index_overhead
    )
    
    return {
        'total_commits': total_commits,
        'total_message_size_bytes': total_message_size,
        'total_message_size_mb': total_message_size / (1024 * 1024),
        'total_file_changes': total_file_changes,
        'commits_storage_mb': commits_storage / (1024 * 1024),
        'messages_storage_mb': messages_storage / (1024 * 1024),
        'file_changes_storage_mb': file_changes_storage / (1024 * 1024),
        'projects_storage_mb': projects_storage / (1024 * 1024),
        'index_overhead_mb': index_overhead / (1024 * 1024),
        'total_storage_mb': total_storage / (1024 * 1024),
        'total_storage_gb': total_storage / (1024 * 1024 * 1024),
    }

def scan_directory_recursive(path: Path, git_repos: list, non_git_projects: list, progress: ProgressTracker, checkpoint: CheckpointManager, total_commits: int, depth: int = 0, max_depth: int = 10):
    """
    Recursively scan a directory for Git repositories.
    
    Args:
        path: Path to scan
        git_repos: List to store found git repos
        non_git_projects: List to store non-git directories
        progress: Progress tracker for updates
        checkpoint: Checkpoint manager for saving progress
        total_commits: Total commits across all repos (from quick scan)
        depth: Current recursion depth
        max_depth: Maximum recursion depth to prevent infinite loops
    """
    if depth > max_depth:
        return
    
    analyzed_paths = checkpoint.get_analyzed_paths()
    
    try:
        for item in path.iterdir():
            if not item.is_dir():
                continue
            
            # Skip common directories to ignore
            if item.name in ['node_modules', '.venv', 'venv', '__pycache__', 'target', 'build', 'dist', '.git']:
                continue
            
            git_dir = item / '.git'
            
            if git_dir.exists():
                item_path = str(item)
                
                # Get commit count from quick scan data
                repo_commit_count = 0
                for repo in checkpoint.data['git_repos_found']:
                    if repo['path'] == item_path:
                        repo_commit_count = repo.get('commit_count', 0)
                        break
                
                # Check if already analyzed and if repo has new commits
                if item_path in analyzed_paths:
                    indent = "  " * depth
                    
                    # Get existing analysis
                    existing_repo = None
                    for repo in checkpoint.data['analyzed_repos']:
                        if repo['path'] == item_path:
                            existing_repo = repo
                            break
                    
                    if existing_repo:
                        # Check if repo has new commits
                        try:
                            repo_obj = git.Repo(item)
                            latest_commit = next(repo_obj.iter_commits(max_count=1))
                            latest_commit_date = datetime.fromtimestamp(latest_commit.committed_date).isoformat()
                            last_analyzed_date = existing_repo.get('last_analyzed_date')
                            
                            if last_analyzed_date and latest_commit_date <= existing_repo.get('last_commit_date', ''):
                                # No new commits, skip
                                print(f"\n{indent}⏭️  Skipping (no new commits): {item.name}", flush=True)
                                git_repos.append(existing_repo)
                                progress.increment_analyzed(existing_repo.get('num_commits', 0))
                                continue
                            else:
                                # Has new commits, re-analyze with smart update
                                print(f"\n{indent}🔄 Updating (new commits detected): {item.name}", flush=True)
                                print(f"{indent}   Last analyzed: {last_analyzed_date}", flush=True)
                                print(f"{indent}   Latest commit: {latest_commit_date}", flush=True)
                                # Will re-analyze below, passing last_analyzed_date
                        except:
                            # Error checking, skip
                            print(f"\n{indent}⏭️  Skipping (already analyzed): {item.name}", flush=True)
                            git_repos.append(existing_repo)
                            progress.increment_analyzed(existing_repo.get('num_commits', 0))
                            continue
                    else:
                        continue
                
                indent = "  " * depth
                analyzed_so_far = sum(r.get('num_commits', 0) for r in git_repos)
                
                # Check if this is the repo we were analyzing or needs update
                current_repo_path, current_repo_commit, partial_stats = checkpoint.get_current_repo()
                resume_from = 0
                last_analyzed_date = None
                
                # Check if we have existing analysis for smart update
                for repo in checkpoint.data['analyzed_repos']:
                    if repo['path'] == item_path:
                        last_analyzed_date = repo.get('last_analyzed_date')
                        break
                
                if current_repo_path == item_path:
                    resume_from = current_repo_commit
                    print(f"\n{indent}🔄 Resuming analysis: {item.name} from commit {resume_from}", flush=True)
                elif last_analyzed_date:
                    # Re-analyzing with smart update
                    partial_stats = None
                else:
                    print(f"\n{indent}📦 Analyzing: {item.name}", flush=True)
                    partial_stats = None
                
                print(f"{indent}   Commits: {repo_commit_count:,} / {total_commits:,} total ({(repo_commit_count/total_commits*100):.1f}% of total)", flush=True)
                print(f"{indent}   Progress: {analyzed_so_far:,} / {total_commits:,} commits analyzed ({(analyzed_so_far/total_commits*100):.1f}%)", flush=True)
                
                # Set current repo in checkpoint and progress tracker
                checkpoint.set_current_repo(item_path, resume_from, partial_stats)
                progress.set_current_repo(item.name)
                
                # Progress callback to update commits during analysis
                def progress_callback(commits_processed):
                    current_total = analyzed_so_far + commits_processed
                    progress.update_commits(current_total)
                
                stats = analyze_git_repo(item, progress_callback=progress_callback, checkpoint=checkpoint, resume_from_commit=resume_from, partial_stats=partial_stats, last_analyzed_date=last_analyzed_date)
                git_repos.append(stats)
                
                # Calculate and display incremental storage for this repo
                if 'error' not in stats:
                    repo_storage = estimate_db_storage([stats])
                    running_total_storage = estimate_db_storage(git_repos)
                    print(f"{indent}   ✅ Complete: {stats['num_commits']} commits, {stats['num_authors']} authors, {stats['total_file_changes']:,} file changes", flush=True)
                    print(f"{indent}   💾 Storage: {repo_storage['total_storage_mb']:.2f} MB (commits: {repo_storage['commits_storage_mb']:.2f} MB, messages: {repo_storage['messages_storage_mb']:.2f} MB, files: {repo_storage['file_changes_storage_mb']:.2f} MB)", flush=True)
                    print(f"{indent}   📊 Running total: {running_total_storage['total_storage_mb']:.2f} MB ({running_total_storage['total_storage_gb']:.3f} GB)", flush=True)
                
                checkpoint.save_repo_analysis(stats)
                checkpoint.clear_current_repo()
                progress.clear_current_repo()
                progress.increment_analyzed(stats.get('num_commits', 0))
            else:
                # Check if this might be a project directory (has common project files)
                project_indicators = ['package.json', 'pyproject.toml', 'requirements.txt', 'pom.xml', 'build.gradle', 'Cargo.toml', 'go.mod']
                has_project_file = any((item / indicator).exists() for indicator in project_indicators)
                
                if has_project_file:
                    indent = "  " * depth
                    print(f"\n{indent}📁 Found project (no git): {item.name}", flush=True)
                    non_git_projects.append(str(item))
                    checkpoint.save_non_git_project(str(item))
                
                # Recursively scan subdirectories
                scan_directory_recursive(item, git_repos, non_git_projects, progress, checkpoint, total_commits, depth + 1, max_depth)
    except PermissionError:
        pass
    except Exception as e:
        indent = "  " * depth
        print(f"\n{indent}⚠️  Error scanning {path.name}: {e}", flush=True)

def main():
    """Main analysis function."""
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == '--clear':
        checkpoint = CheckpointManager()
        checkpoint.clear()
        print("✅ Checkpoint cleared. Run again to start fresh.", flush=True)
        return
    
    # Initialize checkpoint manager
    checkpoint = CheckpointManager()
    
    print("=" * 70, flush=True)
    print("🔍 Git Repository Storage Analysis (Recursive)", flush=True)
    print("=" * 70, flush=True)
    print(flush=True)
    
    # Check if resuming
    if checkpoint.is_quick_scan_complete():
        print("🔄 Resuming from checkpoint...", flush=True)
        print(flush=True)
    
    # Get project locations
    locations = [Path(PRIMARY_PROJECT_ROOT).expanduser().resolve()]
    for loc in ADDITIONAL_PROJECT_ROOTS:
        locations.append(Path(loc).expanduser().resolve())
    
    all_stats = []
    git_repos = []
    non_git_projects = []
    
    # Load existing data from checkpoint
    git_repos = checkpoint.data['analyzed_repos'].copy()
    non_git_projects = checkpoint.data['non_git_projects'].copy()
    
    print(f"📁 Scanning {len(locations)} location(s) recursively...", flush=True)
    print(flush=True)
    
    # Phase 1: Quick scan to find git repos and estimate commit counts
    if checkpoint.is_quick_scan_complete():
        print("📊 Phase 1: Skipping (quick scan already complete)", flush=True)
        all_git_repos = checkpoint.get_found_repos()
        total_commits = checkpoint.data['total_commits']
        print(f"   Loaded from checkpoint: {len(all_git_repos)} repos, {total_commits:,} commits", flush=True)
    else:
        print("📊 Phase 1: Finding Git repositories and estimating commit counts...", flush=True)
        all_git_repos = []
        total_commits = 0
        
        for location in locations:
            if not location.exists():
                print(f"⚠️  Location does not exist: {location}", flush=True)
                continue
            
            print(f"  🔎 Scanning: {location}", flush=True)
            estimate = quick_scan_estimate(location, checkpoint=checkpoint)
            all_git_repos.extend(estimate['git_repos'])
            total_commits += estimate['total_commits']
        
        print(f"\n✅ Quick scan complete:", flush=True)
        print(f"   Git repositories found: {len(all_git_repos)}", flush=True)
        print(f"   Total commits: {total_commits:,}", flush=True)
        
        # Mark quick scan as complete
        checkpoint.complete_quick_scan()
    
    # Estimate time based on commit count
    # Assume ~0.5 seconds per 1000 commits for analysis
    remaining_commits = total_commits - sum(r.get('num_commits', 0) for r in git_repos)
    estimated_time = (remaining_commits / 1000) * 0.5
    
    if estimated_time < 60:
        time_str = f"{estimated_time:.1f} seconds"
    elif estimated_time < 3600:
        time_str = f"{estimated_time / 60:.1f} minutes"
    else:
        time_str = f"{estimated_time / 3600:.1f} hours"
    
    print(f"   Estimated analysis time for remaining repos: {time_str}", flush=True)
    print(flush=True)
    
    # Phase 2: Detailed analysis with progress tracking
    print("📊 Phase 2: Detailed analysis of Git repositories...", flush=True)
    print(flush=True)
    
    # Sort repos by commit count (smallest first) for faster initial results
    all_git_repos_sorted = sorted(all_git_repos, key=lambda r: r.get('commit_count', 0))
    print(f"   Processing repos from smallest to largest (by commit count)", flush=True)
    print(flush=True)
    
    analyzed_commits_so_far = sum(r.get('num_commits', 0) for r in git_repos)
    progress = ProgressTracker(len(all_git_repos_sorted), total_commits)
    progress.analyzed_commits = analyzed_commits_so_far
    progress.analyzed_repos = len(git_repos)
    progress.start_updater()
    
    try:
        # Process repos in sorted order (smallest first)
        analyzed_paths = checkpoint.get_analyzed_paths()
        
        for repo_info in all_git_repos_sorted:
            repo_path = Path(repo_info['path'])
            
            if not repo_path.exists():
                continue
            
            item_path = str(repo_path)
            
            # Check if already analyzed and if repo has new commits
            if item_path in analyzed_paths:
                # Get existing analysis
                existing_repo = None
                for repo in checkpoint.data['analyzed_repos']:
                    if repo['path'] == item_path:
                        existing_repo = repo
                        break
                
                if existing_repo:
                    # Check if repo has new commits
                    try:
                        repo_obj = git.Repo(repo_path)
                        latest_commit = next(repo_obj.iter_commits(max_count=1))
                        latest_commit_date = datetime.fromtimestamp(latest_commit.committed_date).isoformat()
                        last_analyzed_date = existing_repo.get('last_analyzed_date')
                        
                        if last_analyzed_date and latest_commit_date <= existing_repo.get('last_commit_date', ''):
                            # No new commits, skip
                            print(f"\n⏭️  Skipping (no new commits): {repo_path.name}", flush=True)
                            git_repos.append(existing_repo)
                            progress.increment_analyzed(existing_repo.get('num_commits', 0))
                            continue
                        else:
                            # Has new commits, re-analyze with smart update
                            print(f"\n🔄 Updating (new commits detected): {repo_path.name}", flush=True)
                            print(f"   Last analyzed: {last_analyzed_date}", flush=True)
                            print(f"   Latest commit: {latest_commit_date}", flush=True)
                    except:
                        # Error checking, skip
                        print(f"\n⏭️  Skipping (already analyzed): {repo_path.name}", flush=True)
                        git_repos.append(existing_repo)
                        progress.increment_analyzed(existing_repo.get('num_commits', 0))
                        continue
            
            # Analyze this repo
            analyzed_so_far = sum(r.get('num_commits', 0) for r in git_repos)
            repo_commit_count = repo_info.get('commit_count', 0)
            
            # Check if this is the repo we were analyzing
            current_repo_path, current_repo_commit, partial_stats = checkpoint.get_current_repo()
            resume_from = 0
            last_analyzed_date = None
            
            # Check if we have existing analysis for smart update
            for repo in checkpoint.data['analyzed_repos']:
                if repo['path'] == item_path:
                    last_analyzed_date = repo.get('last_analyzed_date')
                    break
            
            if current_repo_path == item_path:
                resume_from = current_repo_commit
                print(f"\n🔄 Resuming analysis: {repo_path.name} from commit {resume_from}", flush=True)
            elif last_analyzed_date:
                # Re-analyzing with smart update
                partial_stats = None
            else:
                print(f"\n� Analyzing: {repo_path.name}", flush=True)
                partial_stats = None
            
            if total_commits > 0:
                print(f"   Commits: {repo_commit_count:,} / {total_commits:,} total ({(repo_commit_count/total_commits*100):.1f}% of total)", flush=True)
                print(f"   Progress: {analyzed_so_far:,} / {total_commits:,} commits analyzed ({(analyzed_so_far/total_commits*100):.1f}%)", flush=True)
            else:
                print(f"   Commits: {repo_commit_count:,}", flush=True)
                print(f"   Progress: {analyzed_so_far:,} commits analyzed", flush=True)
            
            # Set current repo in checkpoint and progress tracker
            checkpoint.set_current_repo(item_path, resume_from, partial_stats)
            progress.set_current_repo(repo_path.name)
            
            # Progress callback to update commits during analysis
            def progress_callback(commits_processed):
                current_total = analyzed_so_far + commits_processed
                progress.update_commits(current_total)
            
            stats = analyze_git_repo(repo_path, progress_callback=progress_callback, checkpoint=checkpoint, resume_from_commit=resume_from, partial_stats=partial_stats, last_analyzed_date=last_analyzed_date)
            git_repos.append(stats)
            
            # Calculate and display incremental storage for this repo
            if 'error' not in stats:
                repo_storage = estimate_db_storage([stats])
                running_total_storage = estimate_db_storage(git_repos)
                
                unique = stats.get('num_commits_unique', stats['num_commits'])
                dups = stats.get('num_commits_duplicate', 0)
                
                print(f"   ✅ Complete: {stats['num_commits']} commits ({unique} unique, {dups} duplicates), {stats['num_authors']} authors, {stats['total_file_changes']:,} file changes", flush=True)
                print(f"   💾 Storage: {repo_storage['total_storage_mb']:.2f} MB (commits: {repo_storage['commits_storage_mb']:.2f} MB, messages: {repo_storage['messages_storage_mb']:.2f} MB, files: {repo_storage['file_changes_storage_mb']:.2f} MB)", flush=True)
                print(f"   📊 Running total: {running_total_storage['total_storage_mb']:.2f} MB ({running_total_storage['total_storage_gb']:.3f} GB)", flush=True)
                
                if dups > 0:
                    print(f"   🔄 Deduplication: Skipped {dups} commits already analyzed in other repos", flush=True)
            
            checkpoint.save_repo_analysis(stats)
            checkpoint.clear_current_repo()
            progress.clear_current_repo()
            progress.increment_analyzed(stats.get('num_commits', 0))
    finally:
        progress.stop_updater()
    
    print(flush=True)
    print("=" * 70, flush=True)
    print("📊 Analysis Results", flush=True)
    print("=" * 70, flush=True)
    print(flush=True)
    
    # Summary
    print(f"Total locations scanned: {len(locations)}", flush=True)
    print(f"Git repositories found: {len(all_git_repos)}", flush=True)
    print(f"Git repositories analyzed: {len(git_repos)}", flush=True)
    print(f"Non-git projects excluded: {len(non_git_projects)}", flush=True)
    print(flush=True)
    
    print(flush=True)
    print("=" * 70, flush=True)
    print("📊 Analysis Results", flush=True)
    print("=" * 70, flush=True)
    print(flush=True)
    
    # Summary
    print(f"Total locations scanned: {len(locations)}", flush=True)
    print(f"Git repositories found: {len(all_git_repos_sorted)}", flush=True)
    print(f"Git repositories analyzed: {len(git_repos)}", flush=True)
    print(f"Non-git projects excluded: {len(non_git_projects)}", flush=True)
    print(flush=True)
    
    # Deduplication summary
    unique_commits = checkpoint.data.get('unique_commits', 0)
    duplicate_commits = checkpoint.data.get('duplicate_commits', 0)
    if duplicate_commits > 0:
        print(f"🔄 Deduplication Summary:", flush=True)
        print(f"   Unique commits analyzed: {unique_commits:,}", flush=True)
        print(f"   Duplicate commits skipped: {duplicate_commits:,}", flush=True)
        print(f"   Deduplication ratio: {(duplicate_commits/(unique_commits+duplicate_commits)*100):.1f}%", flush=True)
        print(flush=True)
    
    if non_git_projects:
        print(f"Excluded non-git projects: {', '.join([Path(p).name for p in non_git_projects[:10]])}", flush=True)
        if len(non_git_projects) > 10:
            print(f"  ... and {len(non_git_projects) - 10} more", flush=True)
        print(flush=True)
    
    # Per-repository details
    print("=" * 70, flush=True)
    print("📦 Repository Details", flush=True)
    print("=" * 70, flush=True)
    print(flush=True)
    
    for stats in git_repos:
        if 'error' in stats:
            print(f"❌ {stats['name']}: {stats['error']}", flush=True)
            continue
        
        print(f"📦 {stats['name']}", flush=True)
        print(f"   Path: {stats['path']}", flush=True)
        print(f"   Commits: {stats['num_commits']:,}", flush=True)
        print(f"   Branches: {stats['num_branches']}", flush=True)
        print(f"   Authors: {stats['num_authors']}", flush=True)
        print(f"   Total message size: {stats['total_commit_message_size'] / 1024:.2f} KB", flush=True)
        print(f"   Avg message size: {stats['avg_commit_message_size']:.1f} bytes", flush=True)
        print(f"   Total file changes: {stats['total_file_changes']:,}", flush=True)
        print(f"   Largest commit: {stats['largest_commit']} files", flush=True)
        
        if stats['commits_by_author']:
            print(f"   Top authors:", flush=True)
            sorted_authors = sorted(stats['commits_by_author'].items(), key=lambda x: x[1], reverse=True)[:3]
            for author, count in sorted_authors:
                print(f"     - {author}: {count} commits", flush=True)
        
        print(flush=True)
    
    # Storage estimation
    print("=" * 70, flush=True)
    print("💾 Database Storage Estimation", flush=True)
    print("=" * 70, flush=True)
    print(flush=True)
    
    storage = estimate_db_storage(git_repos)
    
    print(f"Total commits to store: {storage['total_commits']:,}", flush=True)
    print(f"Total commit message size: {storage['total_message_size_mb']:.2f} MB", flush=True)
    print(f"Total file changes to track: {storage['total_file_changes']:,}", flush=True)
    print(flush=True)
    print("Storage breakdown:", flush=True)
    print(f"  Commit records: {storage['commits_storage_mb']:.2f} MB", flush=True)
    print(f"  Commit messages: {storage['messages_storage_mb']:.2f} MB", flush=True)
    print(f"  File changes: {storage['file_changes_storage_mb']:.2f} MB", flush=True)
    print(f"  Project metadata: {storage['projects_storage_mb']:.2f} MB", flush=True)
    print(f"  Index overhead: {storage['index_overhead_mb']:.2f} MB", flush=True)
    print(flush=True)
    print(f"{'=' * 70}", flush=True)
    print(f"🎯 TOTAL ESTIMATED STORAGE: {storage['total_storage_mb']:.2f} MB ({storage['total_storage_gb']:.3f} GB)", flush=True)
    print(f"{'=' * 70}", flush=True)
    print(flush=True)
    
    # Recommendations
    print("=" * 70, flush=True)
    print("💡 Recommendations", flush=True)
    print("=" * 70, flush=True)
    print(flush=True)
    
    if storage['total_storage_gb'] < 0.1:
        print("✅ Storage requirement is minimal (< 100 MB)", flush=True)
        print("   You can safely store all commit history in the database.", flush=True)
    elif storage['total_storage_gb'] < 1:
        print("⚠️  Storage requirement is moderate (< 1 GB)", flush=True)
        print("   Consider storing only recent commits (e.g., last 1000) or", flush=True)
        print("   implementing a caching strategy with periodic cleanup.", flush=True)
    else:
        print("❌ Storage requirement is significant (> 1 GB)", flush=True)
        print("   Recommendations:", flush=True)
        print("   - Store only recent commits (last 500-1000)", flush=True)
        print("   - Implement a caching layer with TTL", flush=True)
        print("   - Store commit summaries instead of full details", flush=True)
        print("   - Consider using live queries for historical data", flush=True)
    
    print(flush=True)
    
    # Save final results to separate file
    results_file = "storage_analysis_results.json"
    final_results = {
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'total_locations': len(locations),
            'total_git_repos': len(all_git_repos),
            'analyzed_repos': len(git_repos),
            'non_git_projects': len(non_git_projects),
            'storage_estimation': storage
        },
        'git_repos': git_repos,
        'non_git_projects': non_git_projects
    }
    
    try:
        with open(results_file, 'w') as f:
            json.dump(final_results, f, indent=2)
        print(f"💾 Results saved to: {results_file}", flush=True)
    except Exception as e:
        print(f"⚠️  Failed to save results: {e}", flush=True)
    
    # Mark checkpoint as complete
    checkpoint.data['phase'] = 'complete'
    checkpoint.save()
    print(f"💾 Checkpoint saved to: {CHECKPOINT_FILE}", flush=True)
    print(flush=True)
    print("💡 To start fresh, run: python analyze_storage.py --clear", flush=True)
    print(flush=True)

if __name__ == "__main__":
    main()
