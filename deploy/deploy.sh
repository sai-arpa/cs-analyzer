#!/bin/bash
# Deployment script for CS Analyzer on EC2 (Ubuntu)
set -e

APP_DIR="/var/www/cs-analyzer"

echo "🔄 Starting CS Analyzer deployment..."

# 1. Update system and install required packages
echo "📦 Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git

# 2. Ensure we are in the correct directory
if [ "$PWD" != "$APP_DIR" ]; then
    echo "⚠️ Warning: You are not in $APP_DIR. The script assumes the app is located there."
    echo "cd $APP_DIR to continue, or update the APP_DIR variable in this script."
    exit 1
fi

# 3. Setup Virtual Environment
echo "🐍 Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 4. Install Python dependencies
echo "⬇️ Installing Python dependencies..."
pip install -r requirements.txt

# 5. Setup Environment Variables file
if [ ! -f ".env" ]; then
    echo "⚙️ Creating .env file from template..."
    cp .env.example .env
    echo "⚠️ IMPORTANT: Please edit $APP_DIR/.env to add your actual API keys and Database credentials!"
fi

# 6. Configure Systemd Service
echo "⚙️ Configuring systemd service..."
sudo cp deploy/cs-analyzer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cs-analyzer.service
sudo systemctl restart cs-analyzer.service

echo "✅ CS Analyzer deployment complete!"
echo ""
echo "🔍 Helpful Commands:"
echo "- Check service status:  sudo systemctl status cs-analyzer.service"
echo "- View live app logs:    sudo journalctl -u cs-analyzer.service -f"
echo "- Restart application:   sudo systemctl restart cs-analyzer.service"
