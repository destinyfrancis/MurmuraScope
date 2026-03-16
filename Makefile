.PHONY: stop test dev frontend clean

stop:
	@echo "=== Stopping all HKSimEngine Python processes ==="
	pkill -f "run_(twitter|parallel|facebook|instagram)_simulation.py" || true
	pkill -f "uvicorn.*run:app" || true
	pkill -f "uvicorn.*5001" || true
	@echo "=== Done ==="

test: stop
	@echo "=== Running backend tests ==="
	.venv311/bin/python -m pytest backend/tests/ -q --tb=short
	$(MAKE) stop

dev:
	cd backend && ../.venv311/bin/uvicorn run:app --reload --port 5001

frontend:
	cd frontend && npm run dev

clean: stop
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
