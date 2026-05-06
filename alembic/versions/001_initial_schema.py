"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-05-06 15:43:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('project_locations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('path', sa.String(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )
    
    op.create_table('projects',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('path', sa.String(), nullable=False),
    sa.Column('project_type', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('last_commit_hash', sa.String(), nullable=True),
    sa.Column('last_commit_message', sa.Text(), nullable=True),
    sa.Column('last_commit_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_branch', sa.String(), nullable=True),
    sa.Column('location_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['location_id'], ['project_locations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )
    
    op.create_table('journal_entries',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('commit_hashes', sa.ARRAY(sa.String()), nullable=True),
    sa.Column('tags', sa.ARRAY(sa.String()), nullable=True),
    sa.Column('blockers', sa.Text(), nullable=True),
    sa.Column('entry_type', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_journal_entries_date', 'journal_entries', ['date'])
    op.create_index('idx_journal_entries_project_id', 'journal_entries', ['project_id'])
    op.create_index('idx_projects_name', 'projects', ['name'])
    op.create_index('idx_projects_type', 'projects', ['project_type'])


def downgrade() -> None:
    op.drop_index('idx_projects_type', table_name='projects')
    op.drop_index('idx_projects_name', table_name='projects')
    op.drop_index('idx_journal_entries_project_id', table_name='journal_entries')
    op.drop_index('idx_journal_entries_date', table_name='journal_entries')
    op.drop_table('journal_entries')
    op.drop_table('projects')
    op.drop_table('project_locations')
