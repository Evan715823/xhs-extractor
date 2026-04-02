#!/bin/bash
# XHS Extractor - One-click cloud deployment script
# Tested on: Ubuntu 22.04 / Debian 12
# Usage: curl -sSL <your-raw-url>/deploy.sh | bash

set -e

echo "========================================"
echo "  XHS Extractor - Cloud Deployment"
echo "========================================"

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "[1/4] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker
    sudo systemctl start docker
else
    echo "[1/4] Docker already installed, skipping..."
fi

# 2. Install Docker Compose plugin if not present
if ! docker compose version &> /dev/null; then
    echo "[2/4] Installing Docker Compose..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
else
    echo "[2/4] Docker Compose already installed, skipping..."
fi

# 3. Clone or update project
PROJECT_DIR="$HOME/xhs-extractor"
if [ -d "$PROJECT_DIR" ]; then
    echo "[3/4] Updating project..."
    cd "$PROJECT_DIR"
    git pull
else
    echo "[3/4] Cloning project..."
    # Replace with your actual repo URL after pushing
    git clone <YOUR_REPO_URL> "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# 4. Setup .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "========================================"
    echo "  IMPORTANT: Edit your .env file!"
    echo "  nano $PROJECT_DIR/.env"
    echo ""
    echo "  Set at minimum:"
    echo "    LLM_API_KEY=xai-your-key-here"
    echo "========================================"
    echo ""
fi

# 5. Build and start
echo "[4/4] Building and starting..."
docker compose up -d --build

echo ""
echo "========================================"
echo "  Deployment complete!"
echo "  Access: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "  Useful commands:"
echo "    docker compose logs -f     # View logs"
echo "    docker compose restart     # Restart"
echo "    docker compose down        # Stop"
echo "    nano $PROJECT_DIR/.env     # Edit config"
echo "========================================"
