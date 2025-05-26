# ADO to GitLab Migration Tool - Architecture

This document provides an overview of the architecture and design of the ADO to GitLab migration tool.

## Overall Structure

The migration tool follows a modular design with clear separation of concerns:

```
+------------------+     +------------------+     +------------------+
|                  |     |                  |     |                  |
|  Azure DevOps    |     |  Migration Tool  |     |  GitLab          |
|  (Source)        +---->+  (Processor)     +---->+  (Destination)   |
|                  |     |                  |     |                  |
+------------------+     +-------+----------+     +------------------+
                                 |
                                 v
                         +-------+----------+
                         |                  |
                         |  Database        |
                         |  (State Tracking)|
                         |                  |
                         +------------------+
```

## Key Components

1. **Configuration Layer**
   - `config.py`: Connection parameters for ADO, GitLab, and database
   - `config_loader.py`: YAML-based configuration for migration mappings and rules
   - `migration_config.yaml`: Detailed mapping rules between ADO and GitLab entities

2. **Client Layer**
   - `ado_client.py`: Azure DevOps API interaction
   - `gitlab_interaction.py`: GitLab API interaction

3. **Processing Layer**
   - `main_migrator.py`: Main orchestration logic
   - `utils.py`: Helper functions for conversion and formatting

4. **Database Layer**
   - `db_models.py`: SQLAlchemy models for state tracking
   - `db_handler.py`: Database operations

5. **Deployment Infrastructure**
   - `Dockerfile`: Container definition
   - `docker-compose.yml`: Multi-container setup

## Data Flow

1. **Work Item Discovery**
   - Query ADO for work items based on configured criteria
   - Batch fetch work item details to optimize API usage

2. **Primary Migration**
   - For each work item, determine target GitLab entity type (issue or epic)
   - Create GitLab entity with mapped fields and metadata
   - Track mapping in database for reference and recovery

3. **Secondary Migration**
   - Migrate comments and attachments
   - Convert ADO states to GitLab labels
   - Map users between systems

4. **Relationship Processing**
   - Link parent/child relationships
   - Convert ADO links to GitLab relationships

## Database Schema

```
+------------------+     +------------------+     +------------------+
| MigrationState   |     | WorkItemMapping  |     | RelationshipMapping|
+------------------+     +------------------+     +------------------+
| id               |     | id               |     | id               |
| start_time       |     | ado_id           |     | source_ado_id    |
| end_time         |     | ado_type         |     | target_ado_id    |
| status           |     | gitlab_id        |     | relationship_type|
| total_items      |     | gitlab_type      |     | migration_state_id|
| processed_items  |     | migration_state_id|    | processed        |
| failed_items     |     | processed_at     |     | processed_at     |
+------------------+     | status           |     | status           |
                         | error_message    |     | error_message    |
                         +------------------+     +------------------+
```

## Error Handling and Resilience

1. **Checkpoint System**
   - Regular state snapshots to database
   - Ability to resume from last successful point

2. **Relationship Retry**
   - Two-phase process for relationships
   - First phase: record all relationships
   - Second phase: process recorded relationships

3. **Parallel Processing**
   - Batch processing for efficiency
   - Configurable thread pool sizes

## Containerization

The application is containerized using Docker with a multi-container setup:

1. **App Container**
   - Python application with dependencies
   - Runs the migration process

2. **Database Container**
   - PostgreSQL for state tracking
   - Persistent volume for data preservation

This architecture enables reliable migration of large work item sets with proper error recovery and state tracking.