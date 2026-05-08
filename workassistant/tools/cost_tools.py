from typing import Dict, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import select, func, and_
from workassistant.models.ai_api_call import AIApiCall
from workassistant.models.commit_summary import CommitSummary
from workassistant.models.project import Project
from workassistant.database import async_session_maker


async def get_scan_cost_summary(
    days: int = 30,
    project_name: Optional[str] = None,
) -> Dict:
    """
    Get AI API cost summary for scan operations.

    Args:
        days: Number of days to look back (default 30)
        project_name: Filter by project name (optional)

    Returns:
        Dictionary with total cost, call count, token breakdown, and per-operation stats
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session_maker() as session:
        query = select(AIApiCall).where(
            AIApiCall.request_timestamp >= since,
            AIApiCall.operation == "commit_summary_generation",
            AIApiCall.success == True,
        )
        result = await session.execute(query)
        calls = result.scalars().all()

        if not calls:
            return {
                "success": True,
                "period_days": days,
                "total_calls": 0,
                "total_cost_usd": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "avg_cost_per_call": 0.0,
                "by_model": {},
            }

        total_cost = float(sum(c.cost_usd for c in calls))
        total_input = sum(c.input_tokens for c in calls)
        total_output = sum(c.output_tokens for c in calls)

        by_model: Dict[str, dict] = {}
        for c in calls:
            m = c.model
            if m not in by_model:
                by_model[m] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_model[m]["calls"] += 1
            by_model[m]["cost_usd"] = round(by_model[m]["cost_usd"] + float(c.cost_usd), 6)
            by_model[m]["tokens"] += c.total_tokens

        # Deduplicated savings estimate
        dup_result = await session.execute(
            select(CommitSummary).where(CommitSummary.ai_skipped == False)
        )
        analyzed = dup_result.scalars().all()
        skipped_count = sum(1 for a in analyzed if a.ai_skipped)

        return {
            "success": True,
            "period_days": days,
            "total_calls": len(calls),
            "total_cost_usd": round(total_cost, 6),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "avg_cost_per_call": round(total_cost / len(calls), 6) if calls else 0.0,
            "by_model": by_model,
        }


async def get_api_cost_history(
    days: int = 90,
    group_by: str = "day",
) -> Dict:
    """
    Get historical AI API cost trends.

    Args:
        days: Number of days of history (default 90)
        group_by: Group results by 'day', 'week', or 'model'

    Returns:
        Dictionary with cost history broken down by the requested grouping
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session_maker() as session:
        result = await session.execute(
            select(AIApiCall)
            .where(AIApiCall.request_timestamp >= since, AIApiCall.success == True)
            .order_by(AIApiCall.request_timestamp.asc())
        )
        calls = result.scalars().all()

        if not calls:
            return {"success": True, "period_days": days, "group_by": group_by, "history": []}

        history: Dict[str, dict] = {}

        for c in calls:
            if group_by == "day":
                key = c.request_timestamp.date().isoformat()
            elif group_by == "week":
                # ISO week
                key = c.request_timestamp.strftime("%Y-W%W")
            elif group_by == "model":
                key = c.model
            else:
                key = c.request_timestamp.date().isoformat()

            if key not in history:
                history[key] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            history[key]["calls"] += 1
            history[key]["cost_usd"] = round(history[key]["cost_usd"] + float(c.cost_usd), 6)
            history[key]["tokens"] += c.total_tokens

        return {
            "success": True,
            "period_days": days,
            "group_by": group_by,
            "total_cost_usd": round(sum(v["cost_usd"] for v in history.values()), 6),
            "history": [{"period": k, **v} for k, v in sorted(history.items())],
        }


async def get_project_cost_breakdown(top_n: int = 20) -> Dict:
    """
    Show AI cost per project (based on commit summaries with API calls).

    Args:
        top_n: Return the top N most expensive projects

    Returns:
        Dictionary with per-project cost breakdown
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(CommitSummary, AIApiCall, Project)
            .join(AIApiCall, CommitSummary.ai_api_call_id == AIApiCall.id, isouter=True)
            .join(Project, CommitSummary.project_id == Project.id)
            .where(CommitSummary.ai_api_call_id != None)
        )
        rows = result.all()

        by_project: Dict[str, dict] = {}
        for cs, api_call, project in rows:
            name = project.name
            if name not in by_project:
                by_project[name] = {
                    "project_name": name,
                    "commits_summarized": 0,
                    "total_cost_usd": 0.0,
                    "total_tokens": 0,
                }
            by_project[name]["commits_summarized"] += 1
            if api_call:
                by_project[name]["total_cost_usd"] = round(
                    by_project[name]["total_cost_usd"] + float(api_call.cost_usd), 6
                )
                by_project[name]["total_tokens"] += api_call.total_tokens

        sorted_projects = sorted(
            by_project.values(),
            key=lambda x: x["total_cost_usd"],
            reverse=True,
        )[:top_n]

        return {
            "success": True,
            "projects": sorted_projects,
            "total_cost_usd": round(sum(p["total_cost_usd"] for p in sorted_projects), 6),
        }
