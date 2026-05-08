from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from .base import Base


class CommitSHARegistry(Base):
    __tablename__ = "commit_sha_registry"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    commit_sha = Column(String, nullable=False, unique=True, index=True)
    first_project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    analysis_count = Column(Integer, nullable=False, server_default='1')
