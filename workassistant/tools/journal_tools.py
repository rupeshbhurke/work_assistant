from typing import List, Dict, Optional
from datetime import datetime, date
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from workassistant.models.journal_entry import JournalEntry
from workassistant.models.project import Project
from workassistant.database import async_session_maker

async def add_journal_entry(
    summary: str,
    project_name: Optional[str] = None,
    details: Optional[str] = None,
    commit_hashes: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    blockers: Optional[str] = None,
    entry_type: str = "free-form",
    entry_date: Optional[datetime] = None
) -> Dict:
    """
    Create a new journal entry.
    
    Args:
        summary: Brief summary of the work done
        project_name: Name of the project (optional)
        details: Detailed description of the work
        commit_hashes: List of commit hashes referenced
        tags: List of tags for categorization
        blockers: Any blockers encountered
        entry_type: Type of entry ('free-form' or 'guided')
        entry_date: Date of the entry (defaults to now)
        
    Returns:
        Dictionary with result
    """
    async with async_session_maker() as session:
        project_id = None
        
        if project_name:
            result = await session.execute(
                select(Project).where(Project.name == project_name)
            )
            project = result.scalar_one_or_none()
            
            if project:
                project_id = project.id
            else:
                return {"error": f"Project not found: {project_name}"}
        
        entry = JournalEntry(
            date=entry_date or datetime.utcnow(),
            project_id=project_id,
            summary=summary,
            details=details,
            commit_hashes=commit_hashes or [],
            tags=tags or [],
            blockers=blockers,
            entry_type=entry_type
        )
        
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        
        return {
            "success": True,
            "entry_id": entry.id,
            "message": "Journal entry created successfully",
            "date": entry.date.isoformat(),
            "project": project_name
        }

async def search_journal(
    query: Optional[str] = None,
    project_name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 20
) -> Dict:
    """
    Search journal entries.
    
    Args:
        query: Text to search in summary and details
        project_name: Filter by project name
        tags: Filter by tags (entries matching any tag)
        start_date: Filter entries from this date
        end_date: Filter entries until this date
        limit: Maximum number of results
        
    Returns:
        Dictionary with search results
    """
    async with async_session_maker() as session:
        stmt = select(JournalEntry)
        
        conditions = []
        
        if project_name:
            project_result = await session.execute(
                select(Project).where(Project.name == project_name)
            )
            project = project_result.scalar_one_or_none()
            if project:
                conditions.append(JournalEntry.project_id == project.id)
        
        if start_date:
            conditions.append(JournalEntry.date >= datetime.combine(start_date, datetime.min.time()))
        
        if end_date:
            conditions.append(JournalEntry.date <= datetime.combine(end_date, datetime.max.time()))
        
        if tags:
            tag_conditions = [JournalEntry.tags.contains([tag]) for tag in tags]
            conditions.append(or_(*tag_conditions))
        
        if query:
            search_conditions = [
                JournalEntry.summary.ilike(f"%{query}%"),
                JournalEntry.details.ilike(f"%{query}%")
            ]
            conditions.append(or_(*search_conditions))
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(JournalEntry.date.desc()).limit(limit)
        
        result = await session.execute(stmt)
        entries = result.scalars().all()
        
        project_cache = {}
        results = []
        
        for entry in entries:
            if entry.project_id and entry.project_id not in project_cache:
                proj_result = await session.execute(
                    select(Project).where(Project.id == entry.project_id)
                )
                project = proj_result.scalar_one_or_none()
                if project:
                    project_cache[entry.project_id] = project.name
            
            results.append({
                "id": entry.id,
                "date": entry.date.isoformat(),
                "project": project_cache.get(entry.project_id),
                "summary": entry.summary,
                "details": entry.details,
                "commit_hashes": entry.commit_hashes,
                "tags": entry.tags,
                "blockers": entry.blockers,
                "entry_type": entry.entry_type
            })
        
        return {
            "success": True,
            "count": len(results),
            "entries": results
        }

async def get_recent_journal_entries(days: int = 7, limit: int = 10) -> Dict:
    """
    Get recent journal entries from the last N days.
    
    Args:
        days: Number of days to look back
        limit: Maximum number of entries
        
    Returns:
        Dictionary with recent entries
    """
    from datetime import timedelta
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    return await search_journal(
        start_date=start_date.date(),
        limit=limit
    )

async def get_journal_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict:
    """
    Get a summary of journal entries for a date range.
    
    Args:
        start_date: Start date for summary
        end_date: End date for summary
        
    Returns:
        Dictionary with summary statistics
    """
    async with async_session_maker() as session:
        stmt = select(JournalEntry)
        
        conditions = []
        if start_date:
            conditions.append(JournalEntry.date >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            conditions.append(JournalEntry.date <= datetime.combine(end_date, datetime.max.time()))
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        result = await session.execute(stmt)
        entries = result.scalars().all()
        
        projects = set()
        all_tags = set()
        entries_with_blockers = 0
        
        for entry in entries:
            if entry.project_id:
                projects.add(entry.project_id)
            if entry.tags:
                all_tags.update(entry.tags)
            if entry.blockers:
                entries_with_blockers += 1
        
        return {
            "success": True,
            "total_entries": len(entries),
            "unique_projects": len(projects),
            "unique_tags": list(all_tags),
            "entries_with_blockers": entries_with_blockers,
            "date_range": {
                "start": start_date.isoformat() if start_date else None,
                "end": end_date.isoformat() if end_date else None
            }
        }
