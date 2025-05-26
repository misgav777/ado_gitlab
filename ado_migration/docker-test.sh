#!/bin/bash
set -e

echo "Building Docker containers..."
docker-compose build

echo "Starting PostgreSQL database for testing..."
docker-compose up -d db

echo "Waiting for database to initialize (10 seconds)..."
sleep 10

echo "Running database test in Docker..."
docker-compose run --rm app python test_db.py

echo "Test completed. Stopping containers..."
docker-compose down
