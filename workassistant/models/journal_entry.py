from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, ARRAY
from sqlalchemy.sql import func
from workassistant.models.base import Base

class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime(timezone=True), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    summary = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    commit_hashes = Column(ARRAY(String), nullable=True)
    tags = Column(ARRAY(String), nullable=True)
    blockers = Column(Text, nullable=True)
    entry_type = Column(String, default="free-form", nullable=False)
    commit_summary_ids = Column(ARRAY(Integer), nullable=True)
    auto_generated = Column(Boolean, nullable=False, server_default='false')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
