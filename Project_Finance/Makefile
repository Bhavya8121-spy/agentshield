.PHONY: install data train bench test lint fmt run docker clean

install:
	pip install -r requirements-dev.txt

data:
	python scripts/generate_data.py --households 25 --months 14

train: data
	python scripts/train_classifier.py

bench: data
	python scripts/benchmark.py

test:
	pytest

lint:
	ruff check app tests scripts
	mypy app --ignore-missing-imports
	bandit -q -r app

fmt:
	ruff check --fix app tests scripts

run:
	uvicorn app.main:app --reload --port 8000

docker:
	docker compose up --build

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov coverage.xml .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +