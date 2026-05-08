from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base


class ProjectScanJob(Base):
    """Individual project scan job - child of LocationScanJob."""
    __tablename__ = "project_scan_jobs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=False, unique=True, index=True)
    parent_job_id = Column(String, ForeignKey("scan_jobs.job_id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_path = Column(String, nullable=False)
    project_name = Column(String, nullable=False)
    project_type = Column(String, nullable=True)
    status = Column(String, nullable=False, index=True)
    phase = Column(String, nullable=True)
    progress_percent = Column(Integer, nullable=False, server_default='0')
    commits_total = Column(Integer, nullable=True)
    commits_processed = Column(Integer, nullable=False, server_default='0')
    files_total = Column(Integer, nullable=True)
    files_processed = Column(Integer, nullable=False, server_default='0')
    retry_count = Column(Integer, nullable=False, server_default='0')
    max_retries = Column(Integer, nullable=False, server_default='3')
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    result_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    parent_job = relationship("ScanJob", backref="child_jobs", foreign_keys=[parent_job_id])
    project = relationship("Project", backref="scan_jobs")
