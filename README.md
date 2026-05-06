# Personal Work Assistant

An AI-powered personal assistant that knows your projects, maintains a daily work journal, and answers historical queries about your work.

## Features

- **Project Discovery**: Automatically scans and tracks your Git repositories and project folders
- **Daily Journal**: Maintains structured journal entries with project references and commit tracking
- **Historical Queries**: Search through your work history, journal entries, and Git logs
- **Agentic Memory**: Learns your terminology and workflows over time
- **Multi-location Support**: Configure multiple project root directories

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

- `scan_projects` - Discover and index projects
- `git_log` - Get recent commits from Git repositories
- `git_diff_summary` - Summarize changes in commits
- `search_journal` - Search journal entries
- `add_journal_entry` - Create journal entries
- `list_projects` - List all tracked projects
- `add_project_location` - Add new project root directories

## Configuration

Edit `.env` to configure:
- Database connection (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)
- OpenAI API key
- Primary project root path (e.g., `/mnt/c/RB/Workarea/Repo` for WSL)
- Additional project roots (comma-separated)
- Agent model (default: openai:gpt-4o) - must be in format `provider:model_id`

The DATABASE_URL is automatically constructed from the separate database variables with proper URL encoding.

## Development

The project structure:
```
WorkAssistant/
├── workassistant/          # Main package
│   ├── agents/             # Agent definitions
│   ├── tools/              # Custom tools
│   ├── models/             # Database models
│   └── main.py             # Entry point
├── alembic/                # Database migrations
├── tests/                  # Test suite
├── docker-compose.yml      # Docker configuration
├── Makefile                # Development commands
└── pyproject.toml          # Python dependencies
```

## License

MIT
