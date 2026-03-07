#!/bin/bash
cd /home/ubuntu/dashboard/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Start the server in the background
uvicorn main:app --host 0.0.0.0 --port 8080
