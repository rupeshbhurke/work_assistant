"""FastAPI router for Graphify knowledge graph endpoints."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

from workassistant.scanning.graph_builder import graph_builder
from workassistant.database import async_session_maker
from workassistant.models.project import Project
from workassistant.models.project_graph import ProjectGraph
from sqlalchemy import select

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.post("/{project_id}/build")
async def build_graph(project_id: int):
    """Trigger a Graphify knowledge graph build for a project."""
    result = await graph_builder.build(project_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{project_id}/status")
async def get_graph_status(project_id: int):
    """Get the latest graph build status for a project."""
    return await graph_builder.get_status(project_id)


@router.get("/{project_id}/report")
async def get_graph_report(project_id: int):
    """Get the GRAPH_REPORT.md content and metadata."""
    result = await graph_builder.get_report(project_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{project_id}/view")
async def view_graph(project_id: int):
    """Serve the interactive graph.html for a project."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProjectGraph)
            .where(
                ProjectGraph.project_id == project_id,
                ProjectGraph.build_status == "completed",
            )
            .order_by(ProjectGraph.created_at.desc())
            .limit(1)
        )
        graph = result.scalar_one_or_none()

    if not graph or not graph.graph_html_path:
        raise HTTPException(status_code=404, detail="No graph available for this project")

    html_path = Path(graph.graph_html_path)
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Graph HTML file not found on disk")

    return FileResponse(str(html_path), media_type="text/html")


@router.get("/{project_id}/json")
async def get_graph_json(project_id: int):
    """Serve the graph.json for a project."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProjectGraph)
            .where(
                ProjectGraph.project_id == project_id,
                ProjectGraph.build_status == "completed",
            )
            .order_by(ProjectGraph.created_at.desc())
            .limit(1)
        )
        graph = result.scalar_one_or_none()

    if not graph or not graph.graph_json_path:
        raise HTTPException(status_code=404, detail="No graph JSON available")

    json_path = Path(graph.graph_json_path)
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Graph JSON file not found on disk")

    return FileResponse(str(json_path), media_type="application/json")
