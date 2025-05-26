# Configuration Documentation

This document explains the configuration options for the ADO to GitLab migration tool, including connection parameters, mapping rules, and migration behavior options.

## Configuration Files

The migration tool uses several configuration files:

1. **config.py**: Connection parameters and database settings
2. **migration_config.yaml**: Detailed mapping rules and migration options
3. **.env**: Environment variables for Docker deployment

## Connection Configuration (config.py)

The `config.py` file contains essential connection parameters:

```python
import os

# Azure DevOps configuration
AZURE_ORG_URL = "https://israelmoi-vsts.visualstudio.com/"
AZURE_PROJECT = "Trial Employee Period"
AZURE_PAT = os.getenv('AZURE_PAT')

# GitLab configuration
GITLAB_URL = "https://gitlab.moin.gov.il"
GITLAB_PROJECT_ID = 21  # GitLab numeric ID or path
GITLAB_PAT = os.getenv('GITLAB_PAT')

# Database configuration
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
DB_NAME = os.getenv('DB_NAME', 'ado_gitlab_migration')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')

# Database connection string
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# For local SQLite testing (uncomment for local testing without PostgreSQL)
# DB_URL = "sqlite:///migration.db"
```

Key aspects:
- ADO and GitLab connection parameters
- Environment variable integration for sensitive values
- Database connection configuration
- Support for both PostgreSQL and SQLite

## Migration Configuration (migration_config.yaml)

The YAML configuration file provides detailed mapping rules between ADO and GitLab:

```yaml
# Type mappings: Determine how ADO work item types map to GitLab entities
ado_to_gitlab_type:
  Epic: "epic"  # Maps to GitLab epic
  Feature: "epic"  # Maps to GitLab epic
  "User Story": "issue"  # Maps to GitLab issue
  Task: "issue"  # Maps to GitLab issue
  Bug: "issue"  # Maps to GitLab issue

# Default type if not explicitly mapped
default_gitlab_type: "issue"

# State mappings: Convert ADO states to GitLab labels and actions
ado_state_to_gitlab_labels:
  New:
    labels: ["status::open"]
  "In Progress":
    labels: ["status::in progress"]
  Closed:
    labels: ["status::closed"]
    action: "_close_issue_"  # Special action to close the issue

# Prefix for states not explicitly mapped
unmapped_ado_state_label_prefix: "ado_state::"

# Field mappings
ado_description_fields: 
  - "System.Description"
  - "Microsoft.VSTS.Common.AcceptanceCriteria"

# Priority mapping
ado_priority_field_ref_name: "Microsoft.VSTS.Common.Priority"
ado_priority_to_gitlab_label:
  "1": "priority::high"
  "2": "priority::medium"
  "3": "priority::low"
unmapped_ado_priority_label_prefix: "ado_priority::"

# Migration options
migrate_comments: true
migrate_comment_images: true
migrate_ado_tags: true
ado_tag_label_prefix: "tag::"

# Area path handling
migrate_area_paths_to_labels: true
area_path_label_prefix: "area::"
area_path_handling_strategy: "last_segment_only"  # Options: last_segment_only, full_path, all_segments, all_segments_hierarchical
area_path_level_separator: "\\"
glitlab_area_path_label_separator: "::"

# Iteration path handling
migrate_iteration_paths_to_milestones: true

# User mapping
ado_to_gitlab_user_mapping:
  "john.doe@example.com": "jdoe"
  "jane.smith@example.com": "jsmith"

# Relationship mapping
ado_to_gitlab_link_type_mapping:
  "System.LinkTypes.Hierarchy-Forward": null  # Handled separately for parent/child
  "System.LinkTypes.Hierarchy-Reverse": null  # Handled separately for parent/child
  "System.LinkTypes.Related": "relates_to"
  "Microsoft.VSTS.Common.Affects": "affects"
  "Microsoft.VSTS.Common.Blocks": "blocks"

default_gitlab_link_type: "relates_to"

# Performance tuning
ado_batch_fetch_size: 100
```

Key configuration sections:

### Type Mappings

Defines how ADO work item types map to GitLab entities:

```yaml
ado_to_gitlab_type:
  Epic: "epic"  # Maps to GitLab epic
  Feature: "epic"  # Maps to GitLab epic
  "User Story": "issue"  # Maps to GitLab issue
  Task: "issue"  # Maps to GitLab issue
  Bug: "issue"  # Maps to GitLab issue
```

### State Mappings

Defines how ADO states map to GitLab labels and actions:

```yaml
ado_state_to_gitlab_labels:
  New:
    labels: ["status::open"]
  "In Progress":
    labels: ["status::in progress"]
  Closed:
    labels: ["status::closed"]
    action: "_close_issue_"  # Special action to close the issue
```

### Migration Options

Controls what entities are migrated:

```yaml
migrate_comments: true
migrate_comment_images: true
migrate_ado_tags: true
ado_tag_label_prefix: "tag::"
```

### Path Handling

Controls how ADO paths map to GitLab concepts:

```yaml
# Area path handling
migrate_area_paths_to_labels: true
area_path_label_prefix: "area::"
area_path_handling_strategy: "last_segment_only"  # Options: last_segment_only, full_path, all_segments, all_segments_hierarchical

# Iteration path handling
migrate_iteration_paths_to_milestones: true
```

### User Mapping

Maps ADO users to GitLab users:

```yaml
ado_to_gitlab_user_mapping:
  "john.doe@example.com": "jdoe"
  "jane.smith@example.com": "jsmith"
```

### Relationship Mapping

Maps ADO link types to GitLab relationship types:

```yaml
ado_to_gitlab_link_type_mapping:
  "System.LinkTypes.Hierarchy-Forward": null  # Handled separately for parent/child
  "System.LinkTypes.Hierarchy-Reverse": null  # Handled separately for parent/child
  "System.LinkTypes.Related": "relates_to"
  "Microsoft.VSTS.Common.Affects": "affects"
  "Microsoft.VSTS.Common.Blocks": "blocks"
```

## Environment Variables (.env)

The .env file contains configuration settings for Docker deployment:

```
# Azure DevOps Configuration
AZURE_PAT=your_azure_pat_here

# GitLab Configuration
GITLAB_PAT=your_gitlab_pat_here

# Database Configuration
DB_USER=postgres
DB_PASSWORD=migration_password
DB_NAME=ado_gitlab_migration
DB_HOST=db
DB_PORT=5432
```

## Configuration Loading Process

The `config_loader.py` module handles loading and validating the YAML configuration:

```python
def load_migration_config(filepath="migration_config.yaml"):
    """Load and validate migration configuration from YAML file"""
    try:
        with open(filepath, 'r') as file:
            config = yaml.safe_load(file)
            
        # Validate required configuration sections
        required_sections = [
            'ado_to_gitlab_type',
            'default_gitlab_type'
        ]
        
        for section in required_sections:
            if section not in config:
                logger.critical(f"Required configuration section '{section}' missing in {filepath}")
                return None
                
        # Apply defaults for optional sections
        if 'ado_description_fields' not in config:
            config['ado_description_fields'] = ["System.Description"]
            
        # ... additional validation logic
            
        logger.info(f"Successfully loaded migration configuration from {filepath}")
        return config
    except Exception as e:
        logger.critical(f"Failed to load migration configuration from {filepath}: {e}", exc_info=True)
        return None
```

## Customizing for Your Environment

### Connection Parameters

Modify `config.py` or use environment variables to set your connection parameters:

```python
# Azure DevOps configuration
AZURE_ORG_URL = "https://dev.azure.com/your-organization/"
AZURE_PROJECT = "Your Project Name"
AZURE_PAT = os.getenv('AZURE_PAT')

# GitLab configuration
GITLAB_URL = "https://gitlab.your-domain.com"
GITLAB_PROJECT_ID = 123  # GitLab numeric ID or path
GITLAB_PAT = os.getenv('GITLAB_PAT')
```

### Mapping ADO to GitLab

Customize the YAML configuration to match your specific work item types and states:

```yaml
# Type mappings
ado_to_gitlab_type:
  "Product Backlog Item": "issue"  # For Scrum template
  "Impediment": "issue"  # For Scrum template
  "Feature": "epic"  # Common across templates

# State mappings
ado_state_to_gitlab_labels:
  "To Do":
    labels: ["status::backlog"]
  "Doing":
    labels: ["status::in progress"]
  "Done":
    labels: ["status::done"]
    action: "_close_issue_"
```

### Optimizing for Large Migrations

For large migrations, adjust batch sizes and other performance parameters:

```yaml
# Performance tuning
ado_batch_fetch_size: 200  # Increase for faster migration (default 100)
```