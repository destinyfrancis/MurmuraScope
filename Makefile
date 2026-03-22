.PHONY: stop test test-unit test-int test-all test-changed test-file test-cov test-cov-full dev frontend clean docker-up docker-down docker-dev docker-logs docker-clean

PYTEST = .venv311/bin/python -m pytest

# ── Quick unit tests only (no DB, no HTTP client) ──────────────────
test-unit:
	@echo "=== Unit tests only ==="
	$(PYTEST) -m "not integration and not slow" -q --tb=short

# ── Integration tests only (DB / HTTP client) ─────────────────────
test-int:
	$(PYTEST) -m "integration" -q --tb=short

# ── All tests (full suite) ─────────────────────────────────────────
test-all: stop
	@echo "=== Running ALL backend tests ==="
	$(PYTEST) -q --tb=short
	$(MAKE) stop

# ── Default: unit tests (fast feedback loop) ───────────────────────
test: test-unit

# ── Run tests for files changed since last commit ──────────────────
test-changed:
	@echo "=== Tests for changed files ==="
	@changed=$$(git diff --name-only HEAD -- 'backend/app/' 'backend/data_pipeline/' | \
		sed 's|backend/app/services/\(.*\)\.py|backend/tests/test_\1.py|' | \
		sed 's|backend/app/api/\(.*\)\.py|backend/tests/test_\1.py|' | \
		sed 's|backend/data_pipeline/\(.*\)\.py|backend/tests/test_\1.py|' | \
		sort -u | while read f; do [ -f "$$f" ] && echo "$$f"; done); \
	if [ -z "$$changed" ]; then \
		echo "No matching test files for changed sources."; \
	else \
		echo "$$changed" | xargs $(PYTEST) -q --tb=short; \
	fi

# ── Run a single test file: make test-file F=test_belief_system ────
test-file:
	$(PYTEST) backend/tests/$(F).py -q --tb=short

# ── Unit tests with HTML + terminal coverage report ────────────────
test-cov:
	$(PYTEST) -m "not integration and not slow" \
		--cov=backend/app \
		--cov-report=html:htmlcov \
		--cov-report=term-missing \
		-q --tb=short

# ── All tests with coverage report ─────────────────────────────────
test-cov-full:
	$(PYTEST) \
		--cov=backend/app \
		--cov-report=html:htmlcov \
		--cov-report=term-missing \
		-q --tb=short

# ── Server commands ────────────────────────────────────────────────
stop:
	@echo "=== Stopping all HKSimEngine Python processes ==="
	pkill -f "run_(twitter|parallel|facebook|instagram)_simulation.py" || true
	pkill -f "uvicorn.*run:app" || true
	pkill -f "uvicorn.*5001" || true
	@echo "=== Done ==="

dev:
	cd backend && ../.venv311/bin/uvicorn run:app --reload --port 5001

frontend:
	cd frontend && npm run dev

clean: stop
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# ── Docker commands ────────────────────────────────────────────────────────────
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

docker-logs:
	docker compose logs -f

docker-clean:
	docker compose down -v --rmi local
