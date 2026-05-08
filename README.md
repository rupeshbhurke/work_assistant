# Personal Work Assistant

An AI-powered personal assistant that knows your projects, maintains a daily work journal, and answers historical queries about your work.

## Features

### Core Capabilities

- **Project Discovery**: Automatically scans and tracks your Git repositories and project folders
- **Daily Journal**: Maintains structured journal entries with project references and commit tracking
- **Historical Queries**: Search through your work history, journal entries, and Git logs
- **Agentic Memory**: Learns your terminology and workflows over time
- **Multi-location Support**: Configure multiple project root directories

### Advanced Features

#### 🚀 Granular Query System (3-Tier Architecture)

**Tier 1: Instant Queries (0-100ms)**
- `count_repos_at_location(path)` - Count repos without scanning
- `list_repos_fast(path)` - Quick repo names without metadata
- `check_if_repo(path)` - Instant git repo detection
- `get_cached_project_stats()` - Database-cached statistics
- `search_projects_by_name(pattern)` - Fast project search
- `get_project_locations()` - List configured locations

**Tier 2: Lightweight Queries (100ms-2s)**
- `get_repo_basic_info(path)` - Basic git metadata (branch, last commit)
- `get_repo_commit_count(path)` - Count commits without analyzing
- `get_repos_with_recent_activity(path)` - Find active repos
- `detect_repo_language(path)` - Language detection from files
- `compare_repo_sizes(path)` - Compare repos by commit count

**Tier 3: Deep Scan (seconds to minutes)**
- Full project scanning with AI commit analysis
- File indexing and knowledge graph generation
- Journal entry auto-generation

#### 🔀 Hierarchical Job System

**Fault Isolation**
- One project failure doesn't affect others
- Individual project jobs run independently
- Auto-retry with exponential backoff (max 3 attempts)

**Granular Control**
- Restart specific failed projects without re-scanning everything
- Pause/resume individual project scans
- Cancel problematic projects while others continue

**Better Observability**
- Track per-project progress independently
- See which projects are slow/stuck
- Detailed status for each project with error messages

**Architecture**
```
LocationScanJob (parent)
├── Phase: discovery → spawning → monitoring → done
└── Spawns → ProjectScanJob[] (children)
    ├── Each project runs independently
    ├── Phases: metadata → commits → indexing
    └── Auto-retry on failure
```

#### 💬 Chat History Management

**Conversation Grouping**
- Messages organized into conversations
- Auto-generated conversation titles
- Context loading for AI (configurable window size)

**Message Threading**
- Parent-child message relationships
- Follow-up questions linked to previous messages
- Full thread retrieval API

**Search & Filtering**
- Search conversations by title/summary
- Filter by date range
- Search within conversation messages
- Global message search across all conversations

**Local Date/Time Display**
- Messages show local date and time
- Formatted as "🕐 MMM DD, YYYY at HH:MM"
- User's browser locale automatically used

#### 🕸️ Knowledge Graphs

- Build interactive knowledge graphs for projects
- Identify god nodes and architectural patterns
- Community detection for module organization
- Powered by Graphify

#### 💰 Cost Tracking

- Track AI API costs per scan
- Time-series cost history
- Per-project cost breakdown
- Real-time cost monitoring during scans

#### 📊 Scan Progress Monitoring

- Real-time WebSocket progress updates
- Per-project progress tracking
- Phase-by-phase progress (discovery, metadata, commits, indexing)
- Scan job status dashboard

## Usage

## Setup

### Prerequisites

- Python 3.11+
- Docker
- OpenAI API key

### Installation

1. Clone the repository:
```bash
cd ~/workarea/repo/WorkAssistant
```

2. Copy the example environment file and configure it:
```bash
cp .env.example .env
# Edit .env with your actual values (database password, OpenAI API key, project paths)
```

3. Run the setup command:
```bash
make setup
```

This will:
- Install Python dependencies
- Start the PostgreSQL Docker container
- Run database migrations

## Usage

### Example Queries

The assistant intelligently routes your questions to the fastest appropriate tool:

**Instant Queries (Tier 1)**
```
"How many repos at /path/to/projects?"
"List all repos in my work directory"
"Is /path/to/project a git repository?"
"Show me all configured project locations"
"Find projects named 'auth'"
```

**Lightweight Queries (Tier 2)**
```
"What's the last commit in repo X?"
"How many commits in the authentication service?"
"Which repos had activity this week?"
"What language is this project written in?"
"Compare my projects by size"
```

**Deep Scans (Tier 3)**
```
"Analyze all commits and generate insights"
"Build a knowledge graph for my project"
"Scan my entire workspace with AI analysis"
```

### Start the assistant:

**CLI Mode:**
```bash
make dev
```

**Web UI Mode:**
```bash
make web
```

Then open http://localhost:8000 in your browser for a beautiful chat interface with:
- 💬 Real-time chat with the assistant
- 📊 Token usage and cost tracking displayed with each response
- 💡 Quick suggestion buttons for common tasks
- 🎨 Modern, responsive design
- ⌨️ Keyboard shortcuts (Enter to send)

### Common Commands

- `make up` - Start Docker containers
- `make down` - Stop Docker containers
- `make migrate` - Run database migrations
- `make migrate-create MSG='description'` - Create a new migration
- `make test` - Run tests
- `make clean` - Clean up Python cache files

## Architecture

The assistant uses:
- **Agno SDK** for AI agent orchestration
- **PostgreSQL** for persistent storage
- **Alembic** for database migrations
- **GitPython** for Git repository interaction
- **CLI Interface** for user interaction

### Custom Tools

#### Tier 1: Instant Queries
- `count_repos_at_location(path)` - Count git repos at a location
- `list_repos_fast(path)` - Quick repo listing without git metadata
- `check_if_repo(path)` - Check if path is a git repository
- `get_cached_project_stats(path)` - Get cached project statistics
- `search_projects_by_name(pattern)` - Search projects by name
- `get_project_locations()` - List configured project locations

#### Tier 2: Lightweight Queries
- `get_repo_basic_info(path)` - Get basic git repository info
- `get_repo_commit_count(path, branch, since_days)` - Count commits
- `get_repos_with_recent_activity(path, days)` - Find recently active repos
- `detect_repo_language(path)` - Detect project language
- `compare_repo_sizes(path)` - Compare repos by commit count

#### Tier 3: Deep Scanning & Management
- `scan_projects(path)` - Full project scan with AI analysis
- `check_scan_status(job_id)` - Monitor scan progress
- `list_projects()` - List fully scanned projects
- `git_log(project, limit)` - Get detailed commit history
- `git_diff_summary(project, commit)` - Analyze commit diffs

#### Journal Management
- `add_journal_entry` - Create journal entries
- `search_journal` - Search journal entries
- `get_recent_journal_entries` - Get recent entries
- `get_journal_summary` - Generate work summaries

#### Knowledge Graphs
- `build_project_graph(project)` - Build interactive knowledge graph
- `get_project_graph_report(project)` - Get graph analysis report

#### Cost Tracking
- `get_scan_cost_summary` - Recent scan cost summary
- `get_api_cost_history` - Time-series cost trends
- `get_project_cost_breakdown` - Per-project cost breakdown

#### Logging
- `get_logs` - View recent log entries
- `get_available_log_files` - List available log files

## Configuration

Edit `.env` to configure:
- Database connection (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)
- OpenAI API key
- Primary project root path (e.g., `/mnt/c/RB/Workarea/Repo` for WSL)
- Additional project roots (comma-separated)
- Agent model (default: openai:gpt-4o) - must be in format `provider:model_id`
- Chat context window size (CHAT_CONTEXT_WINDOW_SIZE, default: 10) - Number of previous messages to include in AI context
- Scan workers (SCAN_WORKERS, default: 4) - Parallel workers for project scanning
- Max file size for indexing (MAX_FILE_SIZE_BYTES, default: 1048576) - Files larger than this are skipped

The DATABASE_URL is automatically constructed from the separate database variables with proper URL encoding.

## Database Schema

The system uses PostgreSQL with the following main tables:

- `project_locations` - Configured project root directories
- `projects` - Discovered projects with metadata
- `chat_messages` - Chat history with conversation and threading support
- `conversations` - Conversation groups for chat history
- `journal_entries` - Daily work journal entries
- `commit_summaries` - AI-generated commit summaries
- `file_index` - Indexed project files
- `scan_jobs` - Location scan jobs (parent jobs)
- `project_scan_jobs` - Individual project scan jobs (child jobs)
- `ai_api_calls` - AI API call tracking
- `project_graphs` - Knowledge graph data

### Migrations

Run migrations to create/update database schema:
```bash
make migrate
```

Create a new migration:
```bash
make migrate-create MSG='description'
```

## Development

The project structure:
```
WorkAssistant/
├── workassistant/          # Main package
│   ├── agents/             # Agent definitions
│   ├── tools/              # Custom tools
│   │   ├── project_tools.py      # Project scanning tools
│   │   ├── quick_query_tools.py   # Tier 1 instant queries
│   │   ├── lightweight_scan_tools.py  # Tier 2 lightweight queries
│   │   ├── journal_tools.py        # Journal management
│   │   └── log_tools.py            # Log viewing
│   ├── models/             # Database models
│   │   ├── project.py
│   │   ├── scan_job.py
│   │   ├── project_scan_job.py      # Hierarchical job model
│   │   ├── chat_message.py          # Chat with conversations
│   │   └── conversation.py
│   ├── jobs/               # Background job management
│   │   ├── scan_job_manager.py      # Location scan manager
│   │   └── project_scan_job_manager.py  # Project scan manager
│   ├── scanning/           # Scanning logic
│   │   ├── scanner.py              # Main scanner
│   │   ├── project_processor.py    # Single project processor
│   │   ├── commit_summarizer.py    # AI commit analysis
│   │   ├── journal_generator.py    # Auto journal generation
│   │   └── graph_builder.py        # Knowledge graph builder
│   ├── database.py         # Database configuration
│   ├── config.py           # Configuration settings
│   └── main.py             # Entry point
├── alembic/                # Database migrations
│   └── versions/           # Migration files
├── docs/                   # Documentation
│   └── hierarchical_job_design.md
├── tests/                  # Test suite
├── docker-compose.yml      # Docker configuration
├── Makefile                # Development commands
└── pyproject.toml          # Python dependencies
```

## License

MIT
