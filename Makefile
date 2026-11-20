# Raccourcis de developpement. `make help` pour la liste.

PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help install test test-live lint fmt cov demo council app run clean

help:
	@echo "install   cree $(VENV) et installe le projet avec les dependances de dev"
	@echo "test      execute la suite de tests (hors ligne)"
	@echo "test-live tests d'integration reels (necessite OPENAI_API_KEY / ANTHROPIC_API_KEY)"
	@echo "lint      ruff check + ruff format --check"
	@echo "fmt       formate le code avec ruff"
	@echo "cov       tests + rapport de couverture"
	@echo "demo      run complet avec le provider mock"
	@echo "council   deliberation ChatGPT x Claude x Gemini (mocks hors ligne)"
	@echo "app       lance l'interface web du conseil sur http://localhost:8000"
	@echo "clean     supprime caches et artefacts"

install:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/python -m pytest

test-live:
	$(BIN)/python -m pytest -m live

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

fmt:
	$(BIN)/ruff check . --fix
	$(BIN)/ruff format .

cov:
	$(BIN)/python -m pytest --cov=agents --cov-report=term-missing

demo:
	$(BIN)/python -m agents run "Combien coutent 12 x 249,99 USD, et que dit la documentation sur la securite des outils ?" --verbose

council:
	$(BIN)/python -m agents council "Faut-il un index SQL ou une recherche plein texte pour 50 000 documents ?" --verbose

app:
	$(PY) app/server.py

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov dist build *.egg-info runs
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
