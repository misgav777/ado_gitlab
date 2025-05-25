import os
AZURE_ORG_URL = "https://israelmoi-vsts.visualstudio.com/"
AZURE_PROJECT = "Trial Employee Period"
GITLAB_URL = "https://gitlab.moin.gov.il"
GITLAB_PROJECT_ID = 22  # GitLab numeric ID or path
AZURE_PAT = os.getenv('AZURE_PAT')
GITLAB_PAT = os.getenv('GITLAB_PAT')

# Database configuration
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'migration_password')
DB_NAME = os.getenv('DB_NAME', 'ado_gitlab_migration')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')

# Database connection string
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# For local SQLite testing
# Uncomment for local testing without PostgreSQL
# DB_URL = "sqlite:///migration.db"
