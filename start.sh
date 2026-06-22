#!/bin/bash
set -e
export PYTHONPATH=/app
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log
