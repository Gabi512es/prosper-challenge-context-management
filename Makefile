# Prosper Challenge — run everything from the repo root.
#
# Python 3.11+ is required (pipecat-ai 1.4). `make install` picks the first of
# python3.13, python3.12, python3.11, python3 that is 3.11 or later. Override
# with: make install PYTHON=/path/to/python3.11

VENV := backend/.venv
VENV_PY := $(VENV)/bin/python
PYTHON_CANDIDATES := python3.13 python3.12 python3.11 python3
VERSION_OK := import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
NEEDS_PYTHON := Python 3.11 or later is required. On macOS: brew install python@3.11, then run make install again (or make install PYTHON=/path/to/python3.11).

.PHONY: help install run editor text test clean check-venv

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create backend/.venv with Python 3.11+ and install dependencies
	@set -e; \
	if [ -n "$(PYTHON)" ]; then \
		if ! command -v "$(PYTHON)" >/dev/null 2>&1; then \
			echo "error: PYTHON=$(PYTHON) was not found."; exit 1; \
		fi; \
		if ! "$(PYTHON)" -c '$(VERSION_OK)' 2>/dev/null; then \
			echo "error: PYTHON=$(PYTHON) is Python $$("$(PYTHON)" -c 'import platform; print(platform.python_version())' 2>/dev/null)."; \
			echo "$(NEEDS_PYTHON)"; exit 1; \
		fi; \
		interpreter="$(PYTHON)"; \
	else \
		interpreter=""; \
		for candidate in $(PYTHON_CANDIDATES); do \
			if command -v "$$candidate" >/dev/null 2>&1 && "$$candidate" -c '$(VERSION_OK)' 2>/dev/null; then \
				interpreter="$$candidate"; break; \
			fi; \
		done; \
		if [ -z "$$interpreter" ]; then \
			echo "error: no Python 3.11+ found (tried: $(PYTHON_CANDIDATES))."; \
			if command -v python3 >/dev/null 2>&1; then echo "python3 is Python $$(python3 -c 'import platform; print(platform.python_version())')."; fi; \
			echo "$(NEEDS_PYTHON)"; exit 1; \
		fi; \
	fi; \
	if ! command -v npm >/dev/null 2>&1; then \
		echo "error: npm was not found. Node.js and npm are required for the graph editor. On macOS: brew install node"; exit 1; \
	fi; \
	if [ -x "$(VENV_PY)" ] && ! "$(VENV_PY)" -c '$(VERSION_OK)' 2>/dev/null; then \
		echo "Removing $(VENV): it was created with Python $$("$(VENV_PY)" -c 'import platform; print(platform.python_version())'), 3.11+ is required."; \
		rm -rf "$(VENV)"; \
	fi; \
	echo "Using $$interpreter (Python $$("$$interpreter" -c 'import platform; print(platform.python_version())'))"; \
	"$$interpreter" -m venv "$(VENV)"
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r backend/requirements.txt
	npm --prefix frontend install

check-venv:
	@if [ ! -x "$(VENV_PY)" ]; then \
		echo "error: $(VENV) is missing. Run 'make install' first (needs Python 3.11+)."; exit 1; \
	fi
	@if ! "$(VENV_PY)" -c '$(VERSION_OK)' 2>/dev/null; then \
		echo "error: $(VENV) uses Python $$("$(VENV_PY)" -c 'import platform; print(platform.python_version())'); 3.11+ is required. Run 'make install' again."; exit 1; \
	fi
	@if ! "$(VENV_PY)" -c 'import pipecat, pipecat_flows, loguru, openai, tiktoken' 2>/dev/null; then \
		echo "error: dependencies are missing from $(VENV). Run 'make install' again."; exit 1; \
	fi

run: check-venv ## Run the voice agent (then open http://localhost:7860/client)
	$(VENV_PY) backend/bot.py

editor: check-venv ## Run the graph editor at http://localhost:5173
	@if [ ! -d frontend/node_modules ]; then \
		echo "error: frontend/node_modules is missing. Run 'make install' first."; exit 1; \
	fi
	@$(VENV_PY) backend/editor_api.py & \
	editor_pid=$$!; \
	trap 'kill $$editor_pid 2>/dev/null || true' EXIT INT TERM; \
	npm --prefix frontend run dev

text: check-venv ## Run the legacy Flows agent through the controlled text interface
	$(VENV_PY) backend/text_runner.py

test: check-venv ## Run offline tests (no API calls or usage charges)
	cd backend && RUN_OPENAI_INTEGRATION=0 .venv/bin/python -m unittest discover -s tests -v

clean: ## Remove the venv and Python caches
	rm -rf $(VENV)
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +
