"""Add conversations table and update chat_messages for conversation support

Revision ID: 005
Revises: 004
Create Date: 2026-05-08 06:20:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    # Create conversations table
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, index=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Add conversation_id to chat_messages
    op.add_column('chat_messages', sa.Column('conversation_id', sa.Integer(), nullable=True))
    op.create_index('ix_chat_messages_conversation_id', 'chat_messages', ['conversation_id'])
    
    # Add parent_message_id to chat_messages for threading
    op.add_column('chat_messages', sa.Column('parent_message_id', sa.Integer(), nullable=True))
    op.create_index('ix_chat_messages_parent_message_id', 'chat_messages', ['parent_message_id'])
    
    # Add foreign key constraints
    op.create_foreign_key(
        'fk_chat_messages_conversation_id',
        'chat_messages', 'conversations',
        ['conversation_id'], ['id']
    )
    op.create_foreign_key(
        'fk_chat_messages_parent_message_id',
        'chat_messages', 'chat_messages',
        ['parent_message_id'], ['id']
    )


def downgrade():
    # Drop foreign key constraints
    op.drop_constraint('fk_chat_messages_parent_message_id', 'chat_messages', type_='foreignkey')
    op.drop_constraint('fk_chat_messages_conversation_id', 'chat_messages', type_='foreignkey')
    
    # Drop indexes
    op.drop_index('ix_chat_messages_parent_message_id', table_name='chat_messages')
    op.drop_index('ix_chat_messages_conversation_id', table_name='chat_messages')
    
    # Drop columns
    op.drop_column('chat_messages', 'parent_message_id')
    op.drop_column('chat_messages', 'conversation_id')
    
    # Drop conversations table
    op.drop_table('conversations')
