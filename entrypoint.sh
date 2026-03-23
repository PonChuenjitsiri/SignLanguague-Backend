#!/bin/bash
echo "Starting data seeding..."
python scripts/seed_sign_languages.py
echo "Data seeding complete."
echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8080