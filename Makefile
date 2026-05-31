.PHONY: setup dev test lint format check clean db-up db-down

setup:
	pip install -e ".[dev]"
	pre-commit install

dev:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=nlp --cov=api --cov-report=term-missing

lint:
	ruff check .

format:
	ruff format .

check: lint test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf .coverage

db-up:
	docker-compose up -d postgres redis

db-down:
	docker-compose down
