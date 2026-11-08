# Prosper Challenge — run everything from the repo root.

VENV := backend/.venv
PYTHON := $(VENV)/bin/python

.PHONY: help install run editor text test clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install dependencies
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r backend/requirements.txt
	npm --prefix frontend install

run: ## Run the voice agent (then open http://localhost:7860/client)
	$(PYTHON) backend/bot.py

editor: ## Run the graph editor at http://localhost:5173
	@$(PYTHON) backend/editor_api.py & \
	editor_pid=$$!; \
	trap 'kill $$editor_pid 2>/dev/null || true' EXIT INT TERM; \
	npm --prefix frontend run dev

text: ## Run the same agent through the controlled text interface
	$(PYTHON) backend/text_runner.py

test: ## Run offline tests (no API calls or usage charges)
	cd backend && .venv/bin/python -m unittest discover -s tests -v

clean: ## Remove the venv and Python caches
	rm -rf $(VENV)
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +
