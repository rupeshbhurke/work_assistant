from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from workassistant.models.base import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False, unique=True)
    project_type = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String, nullable=True)
    last_commit_hash = Column(String, nullable=True)
    last_commit_message = Column(Text, nullable=True)
    last_commit_date = Column(DateTime(timezone=True), nullable=True)
    current_branch = Column(String, nullable=True)
    location_id = Column(Integer, ForeignKey("project_locations.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_scanned_at = Column(DateTime(timezone=True), nullable=True)
