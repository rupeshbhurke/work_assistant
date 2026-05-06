# Personal Work Assistant — Project Plan

Build a personal AI assistant using the Agno SDK that knows your projects, maintains a daily work journal, and answers historical queries about your work.

## Context & Decisions

| Question | Answer |
|---|---|
| Projects root | Multiple locations (configurable, primary: `c:\RB\Workarea\Repo` + others) |
| Git repos | Many Git Repos, but also plain files and folders |
| UI | Start with AgentOS UI, flexible for later |
| Journal style | Hybrid — free-form notes + guided follow-ups |
| Project location | Under WSL at `~/workarea/repo/WorkAssistant` |

## Architecture

### Agents (Agno multi-agent team or single agent with multiple tools)

1. **Project Scanner Agent / Tool** — Scans configurable project locations (primary: `c:\RB\Workarea\Repo` + others), discovers projects (git repos and plain folders), extracts metadata (name, language, last commit/branch for git repos, description from README if present). Stores a project registry in SQLite with type flag (git vs plain).

2. **Journal Agent** — Handles daily journal entry sessions. Two modes:
   - **Free-form**: User types a summary → agent parses it, asks follow-up questions to link to projects/commits.
   - **Guided**: Agent asks structured questions (What project? What did you do? Any commits to reference? Blockers?).
   - Stores structured journal entries in SQLite with project references, commit hashes, timestamps, tags.

3. **Query Agent** — Answers questions like "Did we work on something like this?" or "What was the last change in this module?" by searching journal entries, git logs, and the project registry.

### Custom Tools to Build

| Tool | Purpose |
|---|---|
| `scan_projects` | Walk configurable project locations, detect git repos and plain folders, read READMEs, extract metadata (with type flag) |
| `git_log` | Run `git log` on a specific git project to get recent commits (only for git repos) |
| `git_diff_summary` | Get a summary of changes in a commit or between dates (only for git repos) |
| `search_journal` | Search journal entries by date, project, keyword, tag |
| `add_journal_entry` | Create a structured journal entry |
| `list_projects` | Return the project registry |
| `add_project_location` | Add a new project root to the configurable list |

### Storage

- **PostgreSQL** via Docker container — stores sessions, memory, journal entries, project registry, project locations configuration
- **Alembic** for database migrations
- **Agentic Memory** — enabled for cross-session context
- **Learning** — enabled so the agent improves over time (learns your project terminology, common workflows)

### Agno SDK Features Used

- `Agent` with custom tools and instructions
- `AgentOS` for serving as API
- `PostgresDb` for persistence (async PostgreSQL)
- `enable_agentic_memory=True` for cross-session memory
- `learning=True` for self-improvement
- `add_history_to_context=True` for conversational continuity
- Custom Python tools (functions decorated or passed as callables)

### Infrastructure

- **Docker Compose** for PostgreSQL container
- **Alembic** for database migrations
- **Makefile** with simple commands:
  - `make setup` — install dependencies, start Docker, run migrations
  - `make up` — start Docker containers
  - `make down` — stop Docker containers
  - `make migrate` — run Alembic migrations
  - `make migrate-create` — create new migration
  - `make dev` — start development server
  - `make test` — run tests

**Note:** Environment variables for PostgreSQL connection will be loaded from `.env` file (`DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`)

## Implementation Steps

### Phase 0 — Infrastructure Setup
1. Create project folder under WSL at `~/workarea/repo/WorkAssistant`
2. Set up `docker-compose.yml` with PostgreSQL container
3. Set up `Makefile` with commands (setup, up, down, migrate, dev, test)
4. Set up `alembic.ini` and migrations directory structure
5. Set up `.env.example` and `.env` with database and OpenAI API keys
6. Set up `pyproject.toml` / `requirements.txt` with dependencies (`agno[os]`, `openai`, `gitpython`, `asyncpg`, `alembic`)
7. Create initial Alembic migration for project registry, journal entries, project locations tables
8. Test: `make setup` runs successfully, PostgreSQL container starts, migrations apply

### Phase 1 — Scaffold & Project Discovery
9. Build `scan_projects` tool — walks configurable project locations, detects `.git` folders and plain folders, extracts project metadata with type flag
10. Build `list_projects`, `add_project_location`, and `git_log` tools (git_log only for git repos)
11. Create the main agent with project-awareness instructions, configured with PostgresDb
12. Test: "What projects do I have?" / "Show me recent commits in project X" / "Add this new project location"

**Note:** Project runs in WSL environment; ensure Windows paths (like `c:\RB\Workarea\Repo`) are accessible via `/mnt/c/RB/Workarea/Repo` or WSL mount points.

### Phase 2 — Journal System
13. Design journal entry schema (date, project, summary, commits, tags, blockers)
14. Build `add_journal_entry` and `search_journal` tools
15. Add journal-mode instructions — agent asks follow-up questions to enrich entries
16. Test: End-of-day journal session, free-form and guided

### Phase 3 — Query & Search
17. Build query capabilities — search journal + git history + project registry
18. Add instructions for answering historical questions
19. Test: "Did we work on something like this?", "What was the last change in mystique?"

### Phase 4 — Polish & Serve
20. Wire up AgentOS with all agents/tools
21. Enable learning, memory, tracing
22. Write README with setup instructions
23. Test full end-to-end flow via AgentOS UI

## Open Questions (for later phases)

- Should the agent auto-scan project locations on startup or on-demand?
- How should the agent handle non-git projects for historical queries (file modification tracking, etc.)?
- Should journal entries support attachments (screenshots, links)?
- Do you want weekly/monthly summary reports generated automatically?
- Should the agent integrate with any task management tool (Jira, GitHub Issues, etc.)?
