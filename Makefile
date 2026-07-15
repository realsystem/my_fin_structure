.PHONY: install reinstall dev clean test parse export report providers generate help check-venv ollama-status ollama-start ollama-stop ollama-pull

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
BSP := $(PYTHON) -m src.main

# Ollama settings
OLLAMA_MODEL = qwen2.5vl:3b

# Default target
help:
	@echo "Bank Statement Parser - Available commands:"
	@echo ""
	@echo "  Setup:"
	@echo "    make install       Create venv and install dependencies (if missing)"
	@echo "    make reinstall     Force reinstall all dependencies"
	@echo "    make dev           Install in development mode"
	@echo "    make clean         Remove venv and cache files"
	@echo ""
	@echo "  Usage:"
	@echo "    make parse PDF=statement.pdf              Parse PDF to JSON"
	@echo "    make export PDF=statement.pdf             Export to Google Sheets"
	@echo "    make report PDF=statement.pdf MERCHANT=lowes    Merchant report"
	@echo "    make report PDF=statement.pdf CATEGORY=purchase Filter by category"
	@echo "    make generate PDF=statement.pdf           Generate new provider (wizard)"
	@echo "    make ai-generate PDF=statement.pdf        Generate provider with AI (single pass)"
	@echo "    make learn PDF=statement.pdf              Learn to parse (creates temp provider)"
	@echo "    make parse-temp PDF=statement.pdf         Test a temp provider"
	@echo "    make commit-provider BANK=chase           Promote temp provider to production"
	@echo "    make providers                            List available providers"
	@echo ""
	@echo "  Ollama (Local LLM):"
	@echo "    make ollama-status   Check if Ollama is running"
	@echo "    make ollama-start    Start Ollama and ensure model is available"
	@echo "    make ollama-stop     Stop Ollama"
	@echo "    make ollama-pull MODEL=...    Pull a specific model"
	@echo ""
	@echo "  Testing:"
	@echo "    make test                            Run all provider tests"
	@echo "    make test-quick                      Run tests with short output"
	@echo "    make test-provider PROVIDER=citi     Test specific provider"
	@echo ""
	@echo "  Examples:"
	@echo "    make parse PDF=eStmt_2026-06-19.pdf"
	@echo "    make report PDF=eStmt_2026-06-19.pdf MERCHANT=lowes"
	@echo "    make report PDF=eStmt_2026-06-19.pdf CATEGORY=purchase MIN=100"
	@echo "    make ollama-start && make ai-generate PDF=citi.pdf"

# Check if venv exists
check-venv:
	@test -d $(VENV) || (echo "Creating venv..." && python3 -m venv $(VENV))
	@test -f $(VENV)/.deps_installed || ($(PIP) install --upgrade pip && \
		$(PIP) install pdfplumber click gspread google-auth pytest requests && \
		touch $(VENV)/.deps_installed && \
		echo "Dependencies installed.")

# Setup
install: check-venv
	@echo "Ready. Activate with: source $(VENV)/bin/activate"

reinstall: clean
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install pdfplumber click gspread google-auth
	touch $(VENV)/.deps_installed
	@echo "Done. Activate with: source $(VENV)/bin/activate"

dev: check-venv
	$(PIP) install -e .

clean:
	rm -rf $(VENV)
	rm -rf __pycache__ src/__pycache__ src/*/__pycache__ tests/__pycache__
	rm -rf *.egg-info src/*.egg-info
	rm -rf .pytest_cache
	find . -name "*.pyc" -delete

# Testing
test: install
	$(PYTHON) -m pytest tests/ -v

test-quick: install
	$(PYTHON) -m pytest tests/ -v --tb=short

test-provider: install
ifndef PROVIDER
	$(error PROVIDER is required. Usage: make test-provider PROVIDER=citi)
endif
	$(PYTHON) -m pytest tests/test_providers.py -v -k "$(PROVIDER)"

# Commands
parse: install
ifndef PDF
	$(error PDF is required. Usage: make parse PDF=statement.pdf)
endif
	@$(BSP) parse "$(PDF)" $(if $(OUTPUT),-o $(OUTPUT))

export: install
ifndef PDF
	$(error PDF is required. Usage: make export PDF=statement.pdf CREDS=credentials.json)
endif
ifndef CREDS
	$(error CREDS is required. Usage: make export PDF=statement.pdf CREDS=credentials.json)
endif
	@$(BSP) export "$(PDF)" -c $(CREDS) $(if $(SHEET),-s "$(SHEET)")

report: install
ifndef PDF
	$(error PDF is required. Usage: make report PDF=statement.pdf MERCHANT=lowes)
endif
	@$(BSP) report "$(PDF)" $(if $(MERCHANT),-m "$(MERCHANT)") $(if $(CATEGORY),-c $(CATEGORY)) $(if $(FROM),--from $(FROM)) $(if $(TO),--to $(TO)) $(if $(MIN),--min-amount $(MIN)) $(if $(MAX),--max-amount $(MAX)) $(if $(FORMAT),--format $(FORMAT))

generate: install
ifndef PDF
	$(error PDF is required. Usage: make generate PDF=statement.pdf)
endif
	@$(BSP) generate-provider "$(PDF)" $(if $(OUTPUT),-o $(OUTPUT)) $(if $(CONFIG),-c $(CONFIG)) $(if $(SAVE_CONFIG),--save-config $(SAVE_CONFIG))

ai-generate: install
ifndef PDF
	$(error PDF is required. Usage: make ai-generate PDF=statement.pdf)
endif
	@$(BSP) ai-generate "$(PDF)" $(if $(OUTPUT),-o $(OUTPUT)) $(if $(MODEL),-m $(MODEL)) $(if $(SAVE_CONFIG),--save-config $(SAVE_CONFIG))

learn: install
ifndef PDF
	$(error PDF is required. Usage: make learn PDF=statement.pdf)
endif
	@$(BSP) learn "$(PDF)" $(if $(MODEL),-m $(MODEL)) $(if $(MAX_ITER),-n $(MAX_ITER)) $(if $(STATE),-s $(STATE)) --temp

learn-prod: install
ifndef PDF
	$(error PDF is required. Usage: make learn-prod PDF=statement.pdf)
endif
	@$(BSP) learn "$(PDF)" $(if $(MODEL),-m $(MODEL)) $(if $(MAX_ITER),-n $(MAX_ITER)) $(if $(STATE),-s $(STATE)) --no-temp

parse-temp: install
ifndef PDF
	$(error PDF is required. Usage: make parse-temp PDF=statement.pdf)
endif
	@$(BSP) parse-temp "$(PDF)"

commit-provider: install
ifndef BANK
	$(error BANK is required. Usage: make commit-provider BANK=chase)
endif
	$(BSP) commit-provider $(BANK) $(if $(FORCE),-f,)

providers: install
	$(BSP) providers

batch: install
ifndef DIR
	$(error DIR is required. Usage: make batch DIR=./statements CREDS=credentials.json)
endif
ifndef CREDS
	$(error CREDS is required. Usage: make batch DIR=./statements CREDS=credentials.json)
endif
	$(BSP) batch $(DIR) -c $(CREDS) $(if $(SHEET),-s "$(SHEET)",)

# Quick shortcuts for the sample file
demo-parse: install
	$(BSP) parse eStmt_2026-06-19.pdf

demo-lowes: install
	$(BSP) report eStmt_2026-06-19.pdf -m lowes

demo-homedepot: install
	$(BSP) report eStmt_2026-06-19.pdf -m "home depot"

demo-purchases: install
	$(BSP) report eStmt_2026-06-19.pdf -c purchase --min-amount 100

# Ollama management targets
ollama-status:
	@echo "Checking Ollama status..."
	@if pgrep -x "ollama" > /dev/null || curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then \
		echo "✓ Ollama is running"; \
		echo ""; \
		echo "Available models:"; \
		ollama list 2>/dev/null || curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//'; \
	else \
		echo "✗ Ollama is not running"; \
		echo "Start it with: make ollama-start"; \
	fi

ollama-start:
	@echo "Starting Ollama..."
	@if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then \
		echo "✓ Ollama is already running"; \
	else \
		echo "Starting ollama serve in background..."; \
		ollama serve > /dev/null 2>&1 & \
		sleep 2; \
		if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then \
			echo "✓ Ollama started"; \
		else \
			echo "⚠ Ollama may still be starting... wait a moment and try again"; \
		fi; \
	fi
	@echo "Checking for model $(OLLAMA_MODEL)..."
	@if ollama list 2>/dev/null | grep -q "$(OLLAMA_MODEL)"; then \
		echo "✓ Model $(OLLAMA_MODEL) is available"; \
	else \
		echo "Pulling model $(OLLAMA_MODEL)..."; \
		ollama pull $(OLLAMA_MODEL); \
		echo "✓ Model $(OLLAMA_MODEL) ready"; \
	fi

ollama-stop:
	@echo "Stopping Ollama..."
	@pkill -x ollama 2>/dev/null && echo "✓ Ollama stopped" || echo "Ollama was not running"

ollama-pull:
ifndef MODEL
	@echo "Error: MODEL not specified"
	@echo "Usage: make ollama-pull MODEL='qwen2.5vl:3b'"
	@exit 1
endif
	@echo "Pulling model: $(MODEL)..."
	@ollama pull $(MODEL)
	@echo "✓ Model $(MODEL) pulled successfully"
