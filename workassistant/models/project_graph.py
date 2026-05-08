from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from .base import Base


class ProjectGraph(Base):
    __tablename__ = "project_graphs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    graph_version = Column(Integer, nullable=False, server_default='1')
    graph_json_path = Column(String, nullable=True)
    graph_html_path = Column(String, nullable=True)
    report_md = Column(Text, nullable=True)
    nodes_count = Column(Integer, nullable=True)
    edges_count = Column(Integer, nullable=True)
    god_nodes = Column(JSON, nullable=True)
    communities_count = Column(Integer, nullable=True)
    build_status = Column(String, nullable=False, server_default='pending', index=True)
    build_duration_seconds = Column(Integer, nullable=True)
    build_commit_hash = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
