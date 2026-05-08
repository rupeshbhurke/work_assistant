from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from .base import Base


class ScanJob(Base):
    __tablename__ = "scan_jobs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=False, unique=True, index=True)
    location_id = Column(Integer, ForeignKey("project_locations.id"), nullable=False)
    status = Column(String, nullable=False, index=True)
    phase = Column(String, nullable=True)
    progress_percent = Column(Integer, nullable=False, server_default='0')
    current_project = Column(String, nullable=True)
    projects_total = Column(Integer, nullable=True)
    projects_processed = Column(Integer, nullable=False, server_default='0')
    commits_total = Column(Integer, nullable=True)
    commits_processed = Column(Integer, nullable=False, server_default='0')
    files_total = Column(Integer, nullable=True)
    files_processed = Column(Integer, nullable=False, server_default='0')
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    result_summary = Column(JSON, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
