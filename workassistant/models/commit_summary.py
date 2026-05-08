from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base


class CommitSummary(Base):
    __tablename__ = "commit_summaries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    commit_hash = Column(String, nullable=False, index=True)
    commit_sha_registry_id = Column(Integer, ForeignKey("commit_sha_registry.id"), nullable=True)
    author = Column(String, nullable=True)
    commit_date = Column(DateTime(timezone=True), nullable=False, index=True)
    commit_message = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    files_changed = Column(JSON, nullable=True)
    files_added = Column(Integer, nullable=True)
    files_modified = Column(Integer, nullable=True)
    files_deleted = Column(Integer, nullable=True)
    diff_size = Column(Integer, nullable=True)
    language = Column(String, nullable=True)
    complexity_score = Column(Integer, nullable=True)
    ai_skipped = Column(Boolean, nullable=False, server_default='false')
    ai_error = Column(Text, nullable=True)
    ai_api_call_id = Column(Integer, ForeignKey("ai_api_calls.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('project_id', 'commit_hash', name='uq_commit_summary_project_hash'),
    )
    
    # Relationships
    project = relationship("Project", back_populates="commit_summaries")
    api_call = relationship("AIApiCall")
