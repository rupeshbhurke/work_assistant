from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    parent_message_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=True, index=True)
    is_user = Column(Boolean, nullable=False, index=True)
    content = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Text, nullable=True)  # Stored as string to preserve formatting
    model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    conversation = relationship("Conversation", backref="messages")
    parent_message = relationship("ChatMessage", remote_side=[id], backref="replies")
