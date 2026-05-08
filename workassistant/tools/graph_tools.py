from typing import Dict, Optional
from sqlalchemy import select
from workassistant.database import async_session_maker
from workassistant.models.project import Project
from workassistant.scanning.graph_builder import graph_builder


async def build_project_graph(project_name: str) -> Dict:
    """
    Build an interactive knowledge graph for a project using Graphify.
    The build runs in the background. Use get_project_graph_report to check results.

    Args:
        project_name: Name of the project to build a graph for

    Returns:
        Dictionary with build status and graph_id
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Project).where(Project.name == project_name)
        )
        project = result.scalar_one_or_none()
        if not project:
            return {"error": f"Project not found: {project_name}"}

    return await graph_builder.build(project.id)


async def get_project_graph_report(project_name: str) -> Dict:
    """
    Get the knowledge graph report for a project, including god nodes,
    communities, and the full GRAPH_REPORT.md content.

    Args:
        project_name: Name of the project

    Returns:
        Dictionary with graph report, god nodes, stats, and build info
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Project).where(Project.name == project_name)
        )
        project = result.scalar_one_or_none()
        if not project:
            return {"error": f"Project not found: {project_name}"}

    status = await graph_builder.get_status(project.id)
    if status.get("build_status") == "none":
        return {
            "error": f"No knowledge graph built for '{project_name}'. Use build_project_graph('{project_name}') first."
        }

    if status.get("build_status") == "building":
        return {"status": "building", "message": "Graph is still being built. Check back shortly."}

    if status.get("build_status") == "failed":
        return {"status": "failed", "error": status.get("error_message")}

    report = await graph_builder.get_report(project.id)
    return report
