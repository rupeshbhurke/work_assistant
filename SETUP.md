# Work Assistant - Setup Instructions

## Quick Start

Follow these steps to get the Personal Work Assistant up and running:

### 1. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your actual values
nano .env
```

**Required configuration:**
- `POSTGRES_PASSWORD`: Set a secure password for PostgreSQL
- `OPENAI_API_KEY`: Your OpenAI API key
- `DATABASE_URL`: Update with your PostgreSQL password
- `PRIMARY_PROJECT_ROOT`: Path to your main projects folder (e.g., `/mnt/c/RB/Workarea/Repo` for WSL)

### 2. Run Setup

```bash
# This will:
# - Install Python dependencies
# - Start PostgreSQL in Docker
# - Run database migrations
make setup
```

### 3. Start the Application

**CLI Mode:**
```bash
make dev
```

**Web UI Mode (Recommended):**
```bash
make web
```

Then open http://localhost:8000 in your browser for a beautiful chat interface with token tracking and cost display.

## Manual Setup (if make setup fails)

If the automated setup doesn't work, follow these steps:

### Install Dependencies
```bash
pip install -e .
```

### Start PostgreSQL
```bash
docker compose up -d
```

### Wait for PostgreSQL to be ready
```bash
# Check if PostgreSQL is running
docker ps | grep workassistant_db

# Check logs if needed
docker logs workassistant_db
```

### Run Migrations
```bash
alembic upgrade head
```

### Start the Application
```bash
python -m workassistant.main
```

## Verification

Once the application is running, you can verify it's working:

**Web UI:**
1. Open http://localhost:8000 in your browser
2. You should see a beautiful chat interface
3. Try clicking a suggestion button or typing: "What projects do I have?"
4. Check the token usage and cost displayed with each response

**CLI:**
1. You should see a welcome message from the Work Assistant
2. Try asking: "What projects do I have?"
3. Try: "Scan my projects at /path/to/your/projects"

## Common Issues

### PostgreSQL Connection Error

If you see connection errors:
```bash
# Check if PostgreSQL is running
docker ps

# Restart PostgreSQL
make down
make up

# Wait a few seconds, then try migrations again
make migrate
```

### Port 5432 Already in Use

If port 5432 is already in use:
1. Edit `.env` and set `POSTGRES_PORT=5433`
2. The application will automatically use the new port

### Alembic Migration Errors

If migrations fail:
```bash
# Check database connection
docker exec -it workassistant_db psql -U workassistant -d workassistant

# If successful, try running migrations again
alembic upgrade head
```

## Next Steps

After setup, you can:

1. **Add project locations:**
   - "Add this project location: /path/to/projects"

2. **Scan for projects:**
   - "Scan my projects at /mnt/c/RB/Workarea/Repo"

3. **Create journal entries:**
   - "I worked on the authentication module today"
   - The assistant will ask follow-up questions to enrich the entry

4. **Query your work history:**
   - "What did I work on last week?"
   - "Did we work on something like user authentication?"
   - "Show me recent commits in project X"

## Development Commands

- `make up` - Start Docker containers
- `make down` - Stop Docker containers
- `make migrate` - Run database migrations
- `make migrate-create MSG='description'` - Create new migration
- `make dev` - Start development server
- `make test` - Run tests
- `make clean` - Clean Python cache files

## Troubleshooting

### View Application Logs
```bash
# The application runs in the foreground, so logs appear in your terminal
# Press Ctrl+C to stop
```

### View PostgreSQL Logs
```bash
docker logs workassistant_db
```

### Reset Database
```bash
# WARNING: This will delete all data!
make down
docker volume rm workassistant_postgres_data
make up
make migrate
```

## WSL-Specific Notes

If you're running in WSL and want to access Windows paths:

- Windows `C:\` is mounted at `/mnt/c/`
- Example: `C:\RB\Workarea\Repo` becomes `/mnt/c/RB/Workarea/Repo`

Make sure to use the WSL path format in your `.env` file.
