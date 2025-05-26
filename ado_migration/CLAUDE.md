# CLAUDE.md - Assistant Information

## Project Overview

This is an Azure DevOps (ADO) to GitLab migration tool designed to transfer work items, their relationships, comments, attachments, and other metadata from an Azure DevOps project to a GitLab project.

## Project Structure

- **main_migrator.py**: Main orchestration script
- **ado_client.py**: Handles Azure DevOps API interactions
- **gitlab_interaction.py**: Manages GitLab API operations
- **config_loader.py**: Loads and validates migration configurations
- **utils.py**: Helper utilities for formatting and data conversion
- **db_models.py**: Database models for tracking migration state
- **db_handler.py**: Database operations and state management
- **config.py**: Connection parameters and configuration
- **migration_config.yaml**: Mapping rules between ADO and GitLab

## Commands to Remember

### Run Tests

```bash
# Test database integration locally with SQLite
python test_db.py

# Test with Docker and PostgreSQL
./docker-test.sh
```

### Run Migration

```bash
# Run locally
python main_migrator.py

# Run with Docker Compose
./run_migration.sh
```

### Database Management

```bash
# Check migration status
docker-compose exec db psql -U postgres -d ado_gitlab_migration -c "SELECT * FROM migration_state ORDER BY id DESC LIMIT 10;"

# View work item mappings
docker-compose exec db psql -U postgres -d ado_gitlab_migration -c "SELECT ado_type, gitlab_type, status, COUNT(*) FROM work_item_mappings GROUP BY ado_type, gitlab_type, status;"
```

## Required Environment Variables

- **AZURE_PAT**: Azure DevOps Personal Access Token
- **GITLAB_PAT**: GitLab Personal Access Token
- **DB_USER**: Database username (default: postgres)
- **DB_PASSWORD**: Database password
- **DB_NAME**: Database name (default: ado_gitlab_migration)
- **DB_HOST**: Database host (default: localhost, or 'db' in Docker)
- **DB_PORT**: Database port (default: 5432)

## Docker Integration

This project is containerized with Docker for easy deployment:

1. **app**: Python application container running the migration
2. **db**: PostgreSQL database for state tracking

## Known Issues and Solutions

1. **Connection Timeouts**: For large migrations, consider increasing timeouts in API calls
2. **Memory Usage**: Large migrations may require increased memory allocation
3. **Rate Limiting**: Adjust batch sizes and thread counts to avoid API rate limits

## Recommended Improvements

1. Implement a web UI for monitoring migration progress
2. Add support for custom field mappings
3. Enhance error recovery mechanisms
4. Improve logging and diagnostics

## Useful Resources

- [Azure DevOps REST API Reference](https://docs.microsoft.com/en-us/rest/api/azure/devops/)
- [GitLab API Documentation](https://docs.gitlab.com/ee/api/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Python-GitLab Library](https://python-gitlab.readthedocs.io/)

## Developer Notes

When reviewing or modifying the code, pay attention to:

1. Error handling and retries in API interactions
2. Transaction management in database operations
3. Configuration validation to prevent incorrect mappings
4. Proper resource cleanup after migration