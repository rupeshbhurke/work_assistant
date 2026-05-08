"""Add project_graphs table for Graphify integration

Revision ID: 003
Revises: 002
Create Date: 2026-05-07 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('project_graphs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('graph_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('graph_json_path', sa.String(), nullable=True),
        sa.Column('graph_html_path', sa.String(), nullable=True),
        sa.Column('report_md', sa.Text(), nullable=True),
        sa.Column('nodes_count', sa.Integer(), nullable=True),
        sa.Column('edges_count', sa.Integer(), nullable=True),
        sa.Column('god_nodes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('communities_count', sa.Integer(), nullable=True),
        sa.Column('build_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('build_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('build_commit_hash', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_project_graphs_project_id', 'project_graphs', ['project_id'])
    op.create_index('idx_project_graphs_status', 'project_graphs', ['build_status'])


def downgrade() -> None:
    op.drop_index('idx_project_graphs_status', table_name='project_graphs')
    op.drop_index('idx_project_graphs_project_id', table_name='project_graphs')
    op.drop_table('project_graphs')
