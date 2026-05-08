"""
Wraps the Graphify CLI to build knowledge graphs for projects.
Runs as a background task; stores results in project_graphs table.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.database import async_session_maker
from workassistant.models.project import Project
from workassistant.models.project_graph import ProjectGraph
from workassistant.config import GRAPHIFY_OUTPUT_DIR, GRAPHIFY_MAX_FILES


class GraphBuilder:
    """Builds Graphify knowledge graphs for projects."""

    def __init__(self):
        self._active_builds: dict[int, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(self, project_id: int) -> dict:
        """Start a graph build for a project. Returns immediately with status."""
        if project_id in self._active_builds:
            task = self._active_builds[project_id]
            if not task.done():
                return {"status": "already_building", "project_id": project_id}

        async with async_session_maker() as session:
            proj_result = await session.execute(
                select(Project).where(Project.id == project_id)
            )
            project = proj_result.scalar_one_or_none()
            if not project:
                return {"error": f"Project not found: {project_id}"}

            # Create graph record
            graph = ProjectGraph(
                project_id=project_id,
                build_status="building",
                build_commit_hash=project.last_commit_hash,
            )
            session.add(graph)
            await session.commit()
            await session.refresh(graph)
            graph_id = graph.id

        task = asyncio.create_task(
            self._run_build(project_id, graph_id),
            name=f"graphify-build-{project_id}",
        )
        self._active_builds[project_id] = task
        task.add_done_callback(lambda _: self._active_builds.pop(project_id, None))

        return {
            "status": "started",
            "project_id": project_id,
            "graph_id": graph_id,
        }

    async def get_status(self, project_id: int) -> dict:
        """Get the latest graph build status for a project."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectGraph)
                .where(ProjectGraph.project_id == project_id)
                .order_by(ProjectGraph.created_at.desc())
                .limit(1)
            )
            graph = result.scalar_one_or_none()
            if not graph:
                return {"status": "none", "project_id": project_id}
            return self._graph_to_dict(graph)

    async def get_report(self, project_id: int) -> dict:
        """Get the GRAPH_REPORT.md content for a project."""
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
            if not graph:
                return {"error": "No completed graph build found"}
            return {
                "project_id": project_id,
                "report": graph.report_md,
                "god_nodes": graph.god_nodes,
                "nodes_count": graph.nodes_count,
                "edges_count": graph.edges_count,
                "communities_count": graph.communities_count,
                "build_commit_hash": graph.build_commit_hash,
                "built_at": graph.created_at.isoformat() if graph.created_at else None,
            }

    # ------------------------------------------------------------------
    # Background build
    # ------------------------------------------------------------------

    async def _run_build(self, project_id: int, graph_id: int) -> None:
        start = time.time()
        try:
            async with async_session_maker() as session:
                proj_result = await session.execute(
                    select(Project).where(Project.id == project_id)
                )
                project = proj_result.scalar_one_or_none()
                if not project:
                    await self._mark_failed(graph_id, "Project not found")
                    return

                project_path = Path(project.path)
                if not project_path.exists():
                    await self._mark_failed(graph_id, f"Path does not exist: {project.path}")
                    return

                # Prepare output directory
                output_dir = Path(GRAPHIFY_OUTPUT_DIR) / project.name
                output_dir.mkdir(parents=True, exist_ok=True)

                # Run graphify CLI
                cmd = [
                    "graphify",
                    str(project_path),
                    "--output", str(output_dir),
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(project_path),
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=600  # 10 min timeout
                )

                if proc.returncode != 0:
                    error_msg = stderr.decode(errors="ignore")[:2000]
                    await self._mark_failed(graph_id, f"graphify exit code {proc.returncode}: {error_msg}")
                    return

                # Parse outputs
                graph_html = output_dir / "graph.html"
                graph_json = output_dir / "graph.json"
                report_md_file = output_dir / "GRAPH_REPORT.md"

                # Also check graphify-out subdirectory (default output location)
                graphify_out = project_path / "graphify-out"
                if not graph_html.exists() and graphify_out.exists():
                    graph_html = graphify_out / "graph.html"
                    graph_json = graphify_out / "graph.json"
                    report_md_file = graphify_out / "GRAPH_REPORT.md"

                report_content = ""
                if report_md_file.exists():
                    report_content = report_md_file.read_text(errors="ignore")[:50000]

                nodes_count = 0
                edges_count = 0
                god_nodes = []
                communities_count = 0

                if graph_json.exists():
                    try:
                        data = json.loads(graph_json.read_text(errors="ignore"))
                        nodes_count = len(data.get("nodes", []))
                        edges_count = len(data.get("edges", data.get("links", [])))
                        # Extract god nodes (top 10 by degree)
                        nodes = data.get("nodes", [])
                        if nodes:
                            sorted_nodes = sorted(
                                nodes,
                                key=lambda n: n.get("degree", n.get("connections", 0)),
                                reverse=True,
                            )[:10]
                            god_nodes = [
                                {"id": n.get("id", ""), "label": n.get("label", n.get("id", "")),
                                 "degree": n.get("degree", n.get("connections", 0))}
                                for n in sorted_nodes
                            ]
                        # Count communities
                        communities = set(n.get("community", n.get("group")) for n in nodes if n.get("community") or n.get("group"))
                        communities_count = len(communities)
                    except (json.JSONDecodeError, KeyError):
                        pass

                duration = int(time.time() - start)

                # Update graph record
                await session.execute(
                    update(ProjectGraph)
                    .where(ProjectGraph.id == graph_id)
                    .values(
                        build_status="completed",
                        graph_json_path=str(graph_json) if graph_json.exists() else None,
                        graph_html_path=str(graph_html) if graph_html.exists() else None,
                        report_md=report_content or None,
                        nodes_count=nodes_count,
                        edges_count=edges_count,
                        god_nodes=god_nodes,
                        communities_count=communities_count,
                        build_duration_seconds=duration,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()

        except asyncio.TimeoutError:
            await self._mark_failed(graph_id, "Build timed out (>600s)")
        except asyncio.CancelledError:
            await self._mark_failed(graph_id, "Build cancelled")
        except Exception as exc:
            await self._mark_failed(graph_id, str(exc)[:2000])

    async def _mark_failed(self, graph_id: int, error: str) -> None:
        async with async_session_maker() as session:
            await session.execute(
                update(ProjectGraph)
                .where(ProjectGraph.id == graph_id)
                .values(
                    build_status="failed",
                    error_message=error,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    @staticmethod
    def _graph_to_dict(graph: ProjectGraph) -> dict:
        return {
            "id": graph.id,
            "project_id": graph.project_id,
            "graph_version": graph.graph_version,
            "build_status": graph.build_status,
            "nodes_count": graph.nodes_count,
            "edges_count": graph.edges_count,
            "god_nodes": graph.god_nodes,
            "communities_count": graph.communities_count,
            "build_duration_seconds": graph.build_duration_seconds,
            "build_commit_hash": graph.build_commit_hash,
            "error_message": graph.error_message,
            "created_at": graph.created_at.isoformat() if graph.created_at else None,
        }


# Singleton
graph_builder = GraphBuilder()
