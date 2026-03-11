#!/bin/bash
# HyperTrader - Start both backend and frontend

echo "================================"
echo "  HyperTrader - Starting..."
echo "================================"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Start backend
echo -e "${BLUE}Starting backend...${NC}"
cd backend
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

cd ..

# Start frontend
echo -e "${BLUE}Starting frontend...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

echo -e "${GREEN}Frontend starting on http://localhost:3000${NC}"
npm run dev &
FRONTEND_PID=$!

cd ..

echo ""
echo "================================"
echo -e "  ${GREEN}HyperTrader is running!${NC}"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  Webhook:  http://localhost:8000/api/webhook"
echo "================================"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait and cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
