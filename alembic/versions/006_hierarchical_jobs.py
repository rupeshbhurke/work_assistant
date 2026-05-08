"""Add hierarchical job system with project scan jobs

Revision ID: 006
Revises: 005
Create Date: 2026-05-08 06:45:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    # Create project_scan_jobs table
    op.create_table(
        'project_scan_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('parent_job_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('project_path', sa.String(), nullable=False),
        sa.Column('project_name', sa.String(), nullable=False),
        sa.Column('project_type', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=True),
        sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('commits_total', sa.Integer(), nullable=True),
        sa.Column('commits_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('files_total', sa.Integer(), nullable=True),
        sa.Column('files_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_summary', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['parent_job_id'], ['scan_jobs.job_id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'])
    )
    
    # Create indexes
    op.create_index('ix_project_scan_jobs_job_id', 'project_scan_jobs', ['job_id'], unique=True)
    op.create_index('ix_project_scan_jobs_parent_job_id', 'project_scan_jobs', ['parent_job_id'])
    op.create_index('ix_project_scan_jobs_status', 'project_scan_jobs', ['status'])
    
    # Add hierarchical fields to scan_jobs table
    op.add_column('scan_jobs', sa.Column('job_type', sa.String(), nullable=False, server_default='location_scan'))
    op.add_column('scan_jobs', sa.Column('child_jobs_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scan_jobs', sa.Column('child_jobs_completed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scan_jobs', sa.Column('child_jobs_failed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scan_jobs', sa.Column('child_jobs_running', sa.Integer(), nullable=False, server_default='0'))
    
    # Create indexes on new columns
    op.create_index('ix_scan_jobs_job_type', 'scan_jobs', ['job_type'])


def downgrade():
    # Drop indexes
    op.drop_index('ix_scan_jobs_job_type', table_name='scan_jobs')
    op.drop_index('ix_project_scan_jobs_status', table_name='project_scan_jobs')
    op.drop_index('ix_project_scan_jobs_parent_job_id', table_name='project_scan_jobs')
    op.drop_index('ix_project_scan_jobs_job_id', table_name='project_scan_jobs')
    
    # Drop columns from scan_jobs
    op.drop_column('scan_jobs', 'child_jobs_running')
    op.drop_column('scan_jobs', 'child_jobs_failed')
    op.drop_column('scan_jobs', 'child_jobs_completed')
    op.drop_column('scan_jobs', 'child_jobs_total')
    op.drop_column('scan_jobs', 'job_type')
    
    # Drop project_scan_jobs table
    op.drop_table('project_scan_jobs')
