#!/bin/bash
# Move to backend directory relative to script
cd "$(dirname "$0")/backend"

# Ensure venv exists and is functional
if [ ! -d "venv" ] || [ ! -f "venv/bin/activate" ] || [ ! -f "venv/bin/uvicorn" ]; then
    echo "⚠️  Virtual environment missing or broken. Recreating..."
    rm -rf venv
    
    # Check if python3-venv is installed (on Ubuntu/Debian)
    if ! dpkg -l | grep -q python3-venv; then
        echo "❌ ERROR: python3-venv is missing."
        echo "Please fix this by running: sudo apt update && sudo apt install -y python3-venv"
        exit 1
    fi
    
    python3 -m venv venv
fi

# Activate and install
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Start the server
echo "Starting Dashboard on port 8080..."
uvicorn main:app --host 0.0.0.0 --port 8080
