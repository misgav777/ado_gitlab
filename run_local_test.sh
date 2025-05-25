#!/bin/bash
set -e

echo "Running local database test with SQLite..."
python test_db.py

echo "
To test with Docker Compose PostgreSQL:
1. Start PostgreSQL container:
   docker-compose up -d db

2. Run test with PostgreSQL connection:
   DB_URL='postgresql://postgres:your_db_password_here@localhost:5432/ado_gitlab_migration' python test_db.py

3. Shutdown when done:
   docker-compose down
"