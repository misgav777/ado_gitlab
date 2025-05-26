# ADO to GitLab Migration Tool

A powerful migration tool for transferring work items from Azure DevOps to GitLab, handling issues, epics, relationships, comments, attachments, and other metadata.

## Features

- Migrate work items from ADO to GitLab (as issues or epics)
- Preserve hierarchical relationships
- Migrate comments with author information
- Transfer attachments and images
- Convert ADO states to GitLab labels
- Map users between systems
- Convert ADO iteration paths to GitLab milestones
- Convert ADO area paths to GitLab labels
- Database integration for tracking migration progress
- Dockerized deployment for scalability

## Requirements

- Python 3.9+
- Docker and Docker Compose (for containerized deployment)
- Azure DevOps PAT with read access
- GitLab PAT with write access
- PostgreSQL database (or SQLite for local testing)

## Setup

1. Clone this repository
2. Create a `.env` file from the example:
   ```
   cp .env.example .env
   ```
3. Edit the `.env` file to add your credentials:
   - `AZURE_PAT`: Your Azure DevOps Personal Access Token
   - `GITLAB_PAT`: Your GitLab Personal Access Token
   - `DB_PASSWORD`: A strong password for the PostgreSQL database

## Usage

### Running Locally with SQLite

For testing or small migrations, you can run the tool locally with SQLite:

```bash
# Test database integration
./run_local_test.sh

# Run migration locally
python main_migrator.py
```

### Running with Docker Compose

For larger migrations or production deployments, use Docker Compose:

```bash
# Start migration process
./run_migration.sh

# View logs
docker-compose logs -f app

# Stop migration
docker-compose down
```

### Running on EC2

For large migrations (8000+ work items), deploy on EC2:

1. Launch an EC2 instance (recommended: t3.medium or larger)
2. Install Docker and Docker Compose
3. Clone this repository
4. Configure the `.env` file
5. Run the migration process:
   ```bash
   ./run_migration.sh
   ```

## Configuration

Edit `migration_config.yaml` to customize mappings between ADO and GitLab entities:

- Work item type mappings
- State to label mappings
- User mappings
- Area path handling
- Iteration path handling
- Comment and attachment migration options

## Database Schema

The migration process uses a database to track progress and maintain state:

- `migration_state`: Overall migration job status
- `work_item_mappings`: Mappings between ADO and GitLab items
- `relationship_mappings`: Work item relationships to be processed

## Troubleshooting

If the migration fails:

1. Check the logs: `docker-compose logs app`
2. Examine the database state:
   ```bash
   docker-compose exec db psql -U postgres -d ado_gitlab_migration -c "SELECT * FROM migration_state ORDER BY id DESC LIMIT 1;"
   ```
3. Review failed work items:
   ```bash
   docker-compose exec db psql -U postgres -d ado_gitlab_migration -c "SELECT * FROM work_item_mappings WHERE status = 'failed';"
   ```

## License

[MIT License](LICENSE)