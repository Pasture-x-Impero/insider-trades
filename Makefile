.PHONY: install test lint serve sync seed
install:
	pip install -e ".[dev]"
test:
	python -m pytest -q
lint:
	ruff check insider_trades tests scripts
serve:
	insider-trades serve --reload
sync:
	insider-trades sync
seed:
	python scripts/seed_fixtures.py
