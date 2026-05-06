.PHONY: help setup up down migrate migrate-create dev test clean

help:
	@echo "Personal Work Assistant - Makefile Commands"
	@echo ""
	@echo "  make setup          - Install dependencies, start Docker, run migrations"
	@echo "  make up             - Start Docker containers"
	@echo "  make down           - Stop Docker containers"
	@echo "  make migrate        - Run Alembic migrations"
	@echo "  make migrate-create - Create new Alembic migration (usage: make migrate-create MSG='description')"
	@echo "  make dev            - Start development server"
	@echo "  make test           - Run tests"
	@echo "  make clean          - Clean up Python cache files"

setup:
	@echo "Setting up Personal Work Assistant..."
	pip install -e .
	@echo "Starting Docker containers..."
	docker compose up -d
	@echo "Waiting for PostgreSQL to be ready..."
	sleep 5
	@echo "Running database migrations..."
	alembic upgrade head
	@echo "Setup complete!"

up:
	docker compose up -d

down:
	docker compose down

migrate:
	alembic upgrade head

migrate-create:
	@if [ -z "$(MSG)" ]; then \
		echo "Error: Please provide a migration message using MSG='description'"; \
		exit 1; \
	fi
	alembic revision --autogenerate -m "$(MSG)"

dev:
	python -m workassistant.main

web:
	python -m workassistant.main --web

test:
	pytest tests/ -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
