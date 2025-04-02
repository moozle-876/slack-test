#!/bin/bash

source .env
python run_migrations.py
cd src && uvicorn main:fastapi_app --host 0.0.0.0 --port ${PORT:-8010} --reload