#!/usr/bin/env bash
set -euo pipefail

# HKSimEngine Demo Script
# Usage: ./scripts/demo.sh

echo "=== HKSimEngine Demo ==="

# 1. Check API key
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    echo "ERROR: OPENROUTER_API_KEY not set"
    echo "  export OPENROUTER_API_KEY=sk-or-..."
    exit 1
fi
echo "✓ API key found"

# 2. Kill stray processes
echo "Cleaning up stray processes..."
pkill -f "run_.*_simulation.py" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
sleep 1

# 3. Start backend
echo "Starting backend on port 5001..."
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

.venv311/bin/python -m uvicorn backend.app:app --port 5001 &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:5001/health > /dev/null 2>&1; then
        echo "✓ Backend ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Backend failed to start"
        kill $BACKEND_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

# 4. Quick start simulation
echo "Starting quick simulation..."
RESPONSE=$(curl -sf -X POST http://localhost:5001/api/simulation/quick-start \
    -H "Content-Type: application/json" \
    -d '{"seed_text": "恒生指數跌破15000點，市場恐慌情緒蔓延，多間銀行收緊按揭成數"}')

SESSION_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('session_id',''))" 2>/dev/null || echo "")

if [ -z "$SESSION_ID" ]; then
    echo "ERROR: Failed to start simulation"
    echo "Response: $RESPONSE"
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi
echo "✓ Session started: $SESSION_ID"

# 5. Poll until complete
echo "Waiting for simulation to complete..."
for i in $(seq 1 120); do
    STATUS=$(curl -sf "http://localhost:5001/api/simulation/${SESSION_ID}" | \
        python3 -c "import sys,json; d=json.load(sys.stdin).get('data',{}); print(d.get('status',''))" 2>/dev/null || echo "")
    if [ "$STATUS" = "complete" ] || [ "$STATUS" = "completed" ]; then
        echo "✓ Simulation complete!"
        break
    fi
    if [ "$STATUS" = "failed" ] || [ "$STATUS" = "error" ]; then
        echo "ERROR: Simulation failed"
        break
    fi
    if [ "$i" -eq 120 ]; then
        echo "TIMEOUT: Simulation still running after 2 minutes"
    fi
    sleep 1
done

# 6. Show results
echo ""
echo "=== Results ==="
echo "Session: $SESSION_ID"
echo "Dashboard: http://localhost:5173/dashboard"
echo "Simulation: http://localhost:5173/simulation/$SESSION_ID"
echo ""
echo "Backend running on PID $BACKEND_PID"
echo "Press Ctrl+C to stop, or run: kill $BACKEND_PID"
