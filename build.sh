#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies"
pip install -r backend/requirements.txt

echo "==> Installing Node dependencies"
cd frontend
npm install

echo "==> Building frontend"
npm run build

echo "==> Build complete — dist/ is ready"
