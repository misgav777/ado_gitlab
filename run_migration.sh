#!/bin/bash
set -e

# Generate a default .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example"
    cp .env.example .env
    echo "Please edit the .env file to add your credentials before continuing"
    exit 1
fi

# Build and start the containers
echo "Starting Docker Compose environment..."
docker-compose up -d

# Follow logs from the app container
echo "Following application logs (press Ctrl+C to stop viewing logs):"
docker-compose logs -f app

echo "
Migration process is running in the background.

To view logs again:
  docker-compose logs -f app

To stop the migration:
  docker-compose down

To view database statistics:
  docker-compose exec db psql -U \$DB_USER -d \$DB_NAME -c \"SELECT * FROM migration_state ORDER BY id DESC LIMIT 10;\"
  docker-compose exec db psql -U \$DB_USER -d \$DB_NAME -c \"SELECT ado_type, gitlab_type, status, COUNT(*) FROM work_item_mappings GROUP BY ado_type, gitlab_type, status;\"
"