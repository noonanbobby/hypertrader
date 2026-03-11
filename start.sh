#!/bin/bash
# HyperTrader - Start backend, frontend, and ngrok tunnel

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "================================"
echo "  HyperTrader - Starting..."
echo "================================"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Kill any existing processes on our ports
echo -e "${YELLOW}Cleaning up old processes...${NC}"
for port in 8000 3000 4040; do
  pid=$(lsof -ti :$port 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill $pid 2>/dev/null || true
    echo "  Killed process on port $port"
  fi
done
sleep 1

# Start backend
echo -e "${BLUE}Starting backend...${NC}"
cd "$DIR/backend"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

source venv/Scripts/activate 2>/dev/null || source venv/bin/activate 2>/dev/null
pip install -r requirements.txt -q

echo -e "${GREEN}Backend starting on http://localhost:8000${NC}"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend
echo -e "${BLUE}Starting frontend...${NC}"
cd "$DIR/frontend"
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

echo -e "${GREEN}Frontend starting on http://localhost:3000${NC}"
npm run dev &
FRONTEND_PID=$!

# Wait for backend to be ready before starting ngrok
echo -e "${BLUE}Waiting for backend to be ready...${NC}"
for i in $(seq 1 15); do
  if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
    echo -e "  ${GREEN}Backend ready!${NC}"
    break
  fi
  sleep 1
done

# Start ngrok tunnel
echo -e "${BLUE}Starting ngrok tunnel...${NC}"
if command -v ngrok &> /dev/null; then
    ngrok http 8000 --log=stdout > /dev/null 2>&1 &
    NGROK_PID=$!
    sleep 3

    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | python -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "unavailable")
else
    echo -e "  ${YELLOW}ngrok not found — skipping tunnel${NC}"
    NGROK_PID=""
    NGROK_URL="(ngrok not installed)"
fi

echo ""
echo "========================================="
echo -e "  ${GREEN}HyperTrader is running!${NC}"
echo "========================================="
echo "  Dashboard:  http://localhost:3000"
echo "  API:        http://localhost:8000"
echo "  API Docs:   http://localhost:8000/docs"
echo "  Webhook:    $NGROK_URL/api/webhook"
echo "  ngrok UI:   http://127.0.0.1:4040"
echo "========================================="
echo ""
echo "Press Ctrl+C to stop all services"

# Wait and cleanup on exit
cleanup() {
  echo ""
  echo -e "${YELLOW}Shutting down HyperTrader...${NC}"
  kill $BACKEND_PID $FRONTEND_PID $NGROK_PID 2>/dev/null
  exit 0
}
trap cleanup INT TERM
wait
