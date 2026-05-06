from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from workassistant.models.base import Base

class ProjectLocation(Base):
    __tablename__ = "project_locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, nullable=False, unique=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
