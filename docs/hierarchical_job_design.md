# Hierarchical Job System Design

## Overview

Break project scanning into a two-level job hierarchy:
1. **Location Scan Job** (parent) - Discovery phase only
2. **Project Scan Jobs** (children) - Individual project processing

## Benefits

- **Fault Isolation**: One project failure doesn't affect others
- **Granular Control**: Restart individual projects
- **Better Observability**: Track per-project progress
- **True Parallelization**: Independent job queues
- **Retry Logic**: Exponential backoff per project

## Architecture

```
LocationScanJob (UUID: abc-123)
├── Status: running
├── Phase: discovery → spawning
├── Projects Found: 50
└── Spawns → ProjectScanJob[]
    ├── ProjectScanJob (UUID: def-456, parent: abc-123)
    │   ├── Project: /path/to/repo1
    │   ├── Phases: metadata → commits → indexing
    │   ├── Status: completed
    │   └── Result: {commits: 100, files: 50}
    │
    ├── ProjectScanJob (UUID: ghi-789, parent: abc-123)
    │   ├── Project: /path/to/repo2
    │   ├── Phases: metadata → commits → indexing
    │   ├── Status: failed
    │   ├── Error: "Corrupted git repo"
    │   └── Retry Count: 2
    │
    └── ProjectScanJob (UUID: jkl-012, parent: abc-123)
        ├── Project: /path/to/repo3
        ├── Phases: metadata → commits → indexing
        └── Status: running
```

## Database Schema

### New Table: `project_scan_jobs`

```sql
CREATE TABLE project_scan_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR UNIQUE NOT NULL,
    parent_job_id VARCHAR REFERENCES scan_jobs(job_id),
    project_id INTEGER REFERENCES projects(id),
    project_path VARCHAR NOT NULL,
    project_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,  -- pending, running, completed, failed, cancelled
    phase VARCHAR,  -- metadata, commits, indexing
    progress_percent INTEGER DEFAULT 0,
    commits_total INTEGER,
    commits_processed INTEGER DEFAULT 0,
    files_total INTEGER,
    files_processed INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    error_message TEXT,
    result_summary JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_project_scan_jobs_job_id ON project_scan_jobs(job_id);
CREATE INDEX idx_project_scan_jobs_parent_job_id ON project_scan_jobs(parent_job_id);
CREATE INDEX idx_project_scan_jobs_status ON project_scan_jobs(status);
```

### Updated: `scan_jobs` table

Add fields:
- `job_type` VARCHAR - 'location_scan' or 'project_scan'
- `child_jobs_total` INTEGER - Number of spawned child jobs
- `child_jobs_completed` INTEGER - Completed child jobs
- `child_jobs_failed` INTEGER - Failed child jobs

## Workflow

### 1. User Initiates Scan

```python
job_id = await scan_projects("/path/to/location")
# Returns: LocationScanJob UUID
```

### 2. Location Scan Job (Parent)

**Phase: Discovery**
- Walk filesystem
- Find all projects (git repos + plain folders)
- Save to database
- Update `projects_total`

**Phase: Spawning**
- For each discovered project:
  - Create `ProjectScanJob` record
  - Spawn async task
  - Track in `child_jobs_total`
- Status → `spawning_complete`

**Phase: Monitoring**
- Wait for all child jobs
- Aggregate results
- Status → `completed` when all children done

### 3. Project Scan Jobs (Children)

**Phase: Metadata**
- Extract git metadata
- Detect language
- Save to `projects` table

**Phase: Commits**
- Analyze commits with AI
- Generate summaries
- Save to `commit_summaries`

**Phase: Indexing**
- Index files
- Build knowledge graph
- Generate journal entries

**On Failure**:
- If `retry_count < max_retries`:
  - Increment `retry_count`
  - Restart with exponential backoff
- Else:
  - Status → `failed`
  - Parent continues with other projects

## API Endpoints

### Get Location Scan Status
```
GET /api/scans/{job_id}
Response: {
  job_id, status, phase, progress_percent,
  projects_found, child_jobs_total,
  child_jobs_completed, child_jobs_failed,
  child_jobs: [...]  // Summary of children
}
```

### Get Project Scan Status
```
GET /api/scans/projects/{job_id}
Response: {
  job_id, parent_job_id, project_path,
  status, phase, progress_percent,
  commits_processed, files_processed,
  retry_count, error_message
}
```

### List Project Jobs for Location
```
GET /api/scans/{location_job_id}/projects
Response: [
  {job_id, project_path, status, phase, ...},
  ...
]
```

### Restart Failed Project
```
POST /api/scans/projects/{job_id}/restart
Response: {
  success: true,
  new_job_id: "..."
}
```

### Cancel Project Job
```
POST /api/scans/projects/{job_id}/cancel
```

## Implementation Plan

1. ✅ Create `ProjectScanJob` model
2. ✅ Add migration for `project_scan_jobs` table
3. ✅ Update `ScanJob` model with hierarchy fields
4. ✅ Create `ProjectScanJobManager`
5. ✅ Refactor `ProjectScanner` to work on single project
6. ✅ Update `ScanJobManager` to spawn child jobs
7. ✅ Add restart/retry logic
8. ✅ Update API endpoints
9. ✅ Update UI to show hierarchical progress
10. ✅ Test failure scenarios

## Error Handling

### Transient Errors (Retry)
- Network timeouts
- Temporary file locks
- Rate limiting

### Permanent Errors (Fail Fast)
- Corrupted git repository
- Missing permissions
- Invalid project structure

### Retry Strategy
```python
backoff_seconds = 2 ** retry_count  # Exponential backoff
max_backoff = 300  # 5 minutes max
```

## Monitoring & Observability

### Parent Job Dashboard
- Total projects found
- Jobs running/completed/failed
- Overall progress percentage
- Estimated time remaining

### Project Job Details
- Individual project progress
- Current phase
- Commit/file counts
- Error messages with stack traces
- Retry history

## Migration Strategy

### Phase 1: Add New Tables (Non-breaking)
- Create `project_scan_jobs` table
- Add fields to `scan_jobs`
- Deploy migration

### Phase 2: Implement New Logic (Parallel)
- New code uses hierarchical jobs
- Old scans continue to work
- Gradual rollout

### Phase 3: Deprecate Old Flow
- Mark old single-job scans as deprecated
- Migrate existing jobs to new format
- Remove old code

## Performance Considerations

- **Database**: Index on `parent_job_id`, `status`
- **Concurrency**: Limit concurrent project jobs (configurable)
- **Memory**: Each project job has own session
- **Cleanup**: Archive completed jobs after 30 days
