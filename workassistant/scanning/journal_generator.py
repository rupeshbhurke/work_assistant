from datetime import datetime, date, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.models.journal_entry import JournalEntry
from workassistant.models.project import Project
from workassistant.models.commit_summary import CommitSummary


class JournalAutoGenerator:
    """Creates journal entries automatically from commit summaries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate_for_project(self, project_id: int) -> int:
        """Generate journal entries for all un-journaled commit summaries
        of a project.  Returns the number of entries created."""
        # Load project
        proj_result = await self.session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = proj_result.scalar_one_or_none()
        if project is None:
            return 0

        # Load commits that belong to this project
        result = await self.session.execute(
            select(CommitSummary)
            .where(CommitSummary.project_id == project_id)
            .order_by(CommitSummary.commit_date.asc())
        )
        summaries: List[CommitSummary] = list(result.scalars().all())
        if not summaries:
            return 0

        # Group by (date, author)
        groups: dict = {}
        for cs in summaries:
            day = cs.commit_date.date() if cs.commit_date else date.today()
            author = cs.author or "Unknown"
            key = (day, author)
            groups.setdefault(key, []).append(cs)

        # For each group: skip if a journal entry already exists with
        # the same project / date / auto_generated flag
        created = 0
        for (day, author), commits in groups.items():
            existing = await self.session.execute(
                select(JournalEntry).where(
                    JournalEntry.project_id == project_id,
                    JournalEntry.date >= datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc),
                    JournalEntry.date < datetime.combine(day, datetime.max.time()).replace(tzinfo=timezone.utc),
                    JournalEntry.auto_generated == True,
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            summary_line = (
                f"{author} made {len(commits)} commit(s) on {project.name}"
            )
            details = self._format_details(commits)
            tags = list(filter(None, [project.name, project.language, author]))
            commit_ids = [c.id for c in commits]
            commit_hashes = [c.commit_hash for c in commits]

            entry = JournalEntry(
                date=datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc),
                project_id=project_id,
                summary=summary_line,
                details=details,
                commit_hashes=commit_hashes,
                commit_summary_ids=commit_ids,
                tags=tags,
                entry_type="auto_commit",
                auto_generated=True,
            )
            self.session.add(entry)
            created += 1

        if created:
            await self.session.commit()

        return created

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_details(commits: List[CommitSummary]) -> str:
        lines = []
        for c in commits:
            short_hash = (c.commit_hash or "")[:8]
            text = c.summary or c.commit_message or "(no description)"
            lines.append(f"- {short_hash}: {text}")
        return "\n".join(lines)
