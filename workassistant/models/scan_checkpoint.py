from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.sql import func
from .base import Base


class ProjectScanCheckpoint(Base):
    __tablename__ = "project_scan_checkpoints"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    location_id = Column(Integer, ForeignKey("project_locations.id"), nullable=False)
    scan_id = Column(String, nullable=False, unique=True)
    phase = Column(String, nullable=False)
    projects_found = Column(JSON, nullable=True)
    projects_processed = Column(JSON, nullable=True)
    current_project = Column(String, nullable=True)
    current_operation = Column(String, nullable=True)
    current_commit = Column(String, nullable=True)
    current_file = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    partial_data = Column(JSON, nullable=True)
    worker_id = Column(Integer, nullable=False, server_default='0')
    is_active = Column(Boolean, nullable=False, server_default='true')
