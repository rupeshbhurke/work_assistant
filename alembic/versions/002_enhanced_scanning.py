"""Enhanced scanning with checkpointing and AI summaries

Revision ID: 002
Revises: 001
Create Date: 2026-05-07 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to projects table
    op.add_column('projects', sa.Column('commit_count', sa.Integer(), nullable=True))
    op.add_column('projects', sa.Column('last_analyzed_commit_hash', sa.String(), nullable=True))
    op.add_column('projects', sa.Column('last_analyzed_commit_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('projects', sa.Column('scan_status', sa.String(), nullable=True))
    op.add_column('projects', sa.Column('scan_phase', sa.String(), nullable=True))
    
    # Create ProjectScanCheckpoint table
    op.create_table('project_scan_checkpoints',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('scan_id', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=False),
        sa.Column('projects_found', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('projects_processed', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('current_project', sa.String(), nullable=True),
        sa.Column('current_operation', sa.String(), nullable=True),
        sa.Column('current_commit', sa.String(), nullable=True),
        sa.Column('current_file', sa.String(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('partial_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('worker_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['location_id'], ['project_locations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scan_id')
    )
    op.create_index('idx_scan_checkpoints_location', 'project_scan_checkpoints', ['location_id'])
    op.create_index('idx_scan_checkpoints_active', 'project_scan_checkpoints', ['is_active'])
    
    # Create CommitSHARegistry table for deduplication
    op.create_table('commit_sha_registry',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('commit_sha', sa.String(), nullable=False),
        sa.Column('first_project_id', sa.Integer(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('analysis_count', sa.Integer(), nullable=False, server_default='1'),
        sa.ForeignKeyConstraint(['first_project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('commit_sha')
    )
    op.create_index('idx_commit_sha_registry_sha', 'commit_sha_registry', ['commit_sha'])
    
    # Create AIApiCall table for cost tracking
    op.create_table('ai_api_calls',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('operation', sa.String(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(10, 6), nullable=False),
        sa.Column('request_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('response_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ai_api_calls_model', 'ai_api_calls', ['model'])
    op.create_index('idx_ai_api_calls_operation', 'ai_api_calls', ['operation'])
    op.create_index('idx_ai_api_calls_timestamp', 'ai_api_calls', ['request_timestamp'])
    
    # Create CommitSummary table
    op.create_table('commit_summaries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('commit_hash', sa.String(), nullable=False),
        sa.Column('commit_sha_registry_id', sa.Integer(), nullable=True),
        sa.Column('author', sa.String(), nullable=True),
        sa.Column('commit_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('commit_message', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('files_changed', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('files_added', sa.Integer(), nullable=True),
        sa.Column('files_modified', sa.Integer(), nullable=True),
        sa.Column('files_deleted', sa.Integer(), nullable=True),
        sa.Column('diff_size', sa.Integer(), nullable=True),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('complexity_score', sa.Integer(), nullable=True),
        sa.Column('ai_skipped', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('ai_error', sa.Text(), nullable=True),
        sa.Column('ai_api_call_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['commit_sha_registry_id'], ['commit_sha_registry.id'], ),
        sa.ForeignKeyConstraint(['ai_api_call_id'], ['ai_api_calls.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'commit_hash', name='uq_commit_summary_project_hash')
    )
    op.create_index('idx_commit_summaries_project', 'commit_summaries', ['project_id'])
    op.create_index('idx_commit_summaries_hash', 'commit_summaries', ['commit_hash'])
    op.create_index('idx_commit_summaries_date', 'commit_summaries', ['commit_date'])
    
    # Create FileIndex table
    op.create_table('file_index',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_hash', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('last_modified', sa.DateTime(timezone=True), nullable=False),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('is_binary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_file_index_project_path', 'file_index', ['project_id', 'file_path'])
    op.create_index('idx_file_index_hash', 'file_index', ['file_hash'])
    
    # Create ScanJob table for async operations
    op.create_table('scan_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=True),
        sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_project', sa.String(), nullable=True),
        sa.Column('projects_total', sa.Integer(), nullable=True),
        sa.Column('projects_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('commits_total', sa.Integer(), nullable=True),
        sa.Column('commits_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('files_total', sa.Integer(), nullable=True),
        sa.Column('files_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_summary', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['location_id'], ['project_locations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id')
    )
    op.create_index('idx_scan_jobs_job_id', 'scan_jobs', ['job_id'])
    op.create_index('idx_scan_jobs_status', 'scan_jobs', ['status'])
    
    # Update journal_entries table
    op.add_column('journal_entries', sa.Column('commit_summary_ids', postgresql.ARRAY(sa.Integer()), nullable=True))
    op.add_column('journal_entries', sa.Column('auto_generated', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    # Drop journal_entries columns
    op.drop_column('journal_entries', 'auto_generated')
    op.drop_column('journal_entries', 'commit_summary_ids')
    
    # Drop scan_jobs table
    op.drop_index('idx_scan_jobs_status', table_name='scan_jobs')
    op.drop_index('idx_scan_jobs_job_id', table_name='scan_jobs')
    op.drop_table('scan_jobs')
    
    # Drop file_index table
    op.drop_index('idx_file_index_hash', table_name='file_index')
    op.drop_index('idx_file_index_project_path', table_name='file_index')
    op.drop_table('file_index')
    
    # Drop commit_summaries table
    op.drop_index('idx_commit_summaries_date', table_name='commit_summaries')
    op.drop_index('idx_commit_summaries_hash', table_name='commit_summaries')
    op.drop_index('idx_commit_summaries_project', table_name='commit_summaries')
    op.drop_table('commit_summaries')
    
    # Drop ai_api_calls table
    op.drop_index('idx_ai_api_calls_timestamp', table_name='ai_api_calls')
    op.drop_index('idx_ai_api_calls_operation', table_name='ai_api_calls')
    op.drop_index('idx_ai_api_calls_model', table_name='ai_api_calls')
    op.drop_table('ai_api_calls')
    
    # Drop commit_sha_registry table
    op.drop_index('idx_commit_sha_registry_sha', table_name='commit_sha_registry')
    op.drop_table('commit_sha_registry')
    
    # Drop project_scan_checkpoints table
    op.drop_index('idx_scan_checkpoints_active', table_name='project_scan_checkpoints')
    op.drop_index('idx_scan_checkpoints_location', table_name='project_scan_checkpoints')
    op.drop_table('project_scan_checkpoints')
    
    # Drop projects columns
    op.drop_column('projects', 'scan_phase')
    op.drop_column('projects', 'scan_status')
    op.drop_column('projects', 'last_analyzed_commit_date')
    op.drop_column('projects', 'last_analyzed_commit_hash')
    op.drop_column('projects', 'commit_count')
