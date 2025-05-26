# Docker Deployment Documentation

This document explains the Docker deployment setup for the ADO to GitLab migration tool, which enables containerized execution and scalable deployments.

## Docker Components

### Dockerfile

The Dockerfile defines how the application container is built:

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Command to run when container starts
CMD ["python", "main_migrator.py"]
```

Key aspects:
- Uses Python 3.9 as the base image
- Installs dependencies from requirements.txt
- Copies all application code into the container
- Sets the default command to run the migration script

### docker-compose.yml

The Docker Compose configuration defines the multi-container setup:

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    volumes:
      - ./:/app
    env_file:
      - .env
    depends_on:
      - db
    restart: unless-stopped
    command: python main_migrator.py

  db:
    image: postgres:14-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    env_file:
      - .env
    ports:
      - "5432:5432"
    restart: unless-stopped
    environment:
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=${DB_NAME}

volumes:
  postgres_data:
```

Key aspects:
- Defines two services: app (the migration tool) and db (PostgreSQL)
- Mounts the local directory into the app container for development
- Uses environment variables from .env file
- Sets up persistent storage for PostgreSQL data
- Configures automatic restart for reliability

### Environment Configuration (.env)

The .env file contains configuration settings:

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

## Running with Docker

### Local Development and Testing

For testing, you can use the provided scripts:

```bash
# Test database integration
./docker-test.sh
```

The script performs these steps:
1. Builds the Docker containers
2. Starts the PostgreSQL database
3. Runs the database integration test
4. Cleans up containers when done

### Production Migration

For production migration, use:

```bash
# Start migration process
./run_migration.sh
```

This script:
1. Creates a default .env file if missing
2. Builds and starts the containers
3. Follows logs from the app container
4. Provides commands for monitoring

## EC2 Deployment

For large migrations on EC2, follow these steps:

1. Launch an EC2 instance (recommended t3.medium or larger)

2. Install Docker and Docker Compose:
   ```bash
   sudo yum update -y
   sudo amazon-linux-extras install docker
   sudo service docker start
   sudo usermod -a -G docker ec2-user
   sudo curl -L "https://github.com/docker/compose/releases/download/v2.6.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose
   ```

3. Clone the repository and configure:
   ```bash
   git clone <repository-url>
   cd ado_gitlab
   cp .env.example .env
   # Edit .env with your credentials
   ```

4. Start the migration:
   ```bash
   ./run_migration.sh
   ```

5. For long-running migrations, use screen or tmux:
   ```bash
   sudo yum install screen
   screen -S migration
   ./run_migration.sh
   # Press Ctrl+A, D to detach
   # screen -r migration to reattach
   ```

## Monitoring and Management

### Viewing Logs

```bash
# View application logs
docker-compose logs -f app

# View database logs
docker-compose logs -f db
```

### Database Inspection

```bash
# Connect to PostgreSQL and check migration status
docker-compose exec db psql -U $DB_USER -d $DB_NAME -c "SELECT * FROM migration_state ORDER BY id DESC LIMIT 10;"

# Check work item mappings
docker-compose exec db psql -U $DB_USER -d $DB_NAME -c "SELECT ado_type, gitlab_type, status, COUNT(*) FROM work_item_mappings GROUP BY ado_type, gitlab_type, status;"
```

### Stopping and Cleanup

```bash
# Stop containers but keep volumes
docker-compose down

# Stop containers and remove volumes (deletes all data)
docker-compose down -v
```

## Performance Tuning

For large migrations, consider these adjustments:

1. **PostgreSQL Configuration**:
   Add a custom postgresql.conf volume mount with optimized settings

2. **Container Resources**:
   Add resource limits in docker-compose.yml:
   ```yaml
   app:
     # ... other settings
     deploy:
       resources:
         limits:
           cpus: '2'
           memory: 2G
   ```

3. **Batch Size Tuning**:
   Modify migration_config.yaml to adjust batch sizes:
   ```yaml
   ado_batch_fetch_size: 200  # Default 100
   ```

## Troubleshooting

### Common Issues

1. **Database Connection Failures**:
   - Ensure the DB_HOST is set to 'db' in the .env file when using Docker Compose
   - Check that the PostgreSQL container is running: `docker-compose ps`

2. **Memory Issues**:
   - For large migrations, increase Docker memory allocation
   - Use EC2 instances with sufficient memory (8GB+ recommended for large migrations)

3. **Network Timeouts**:
   - Add retry logic or use the built-in retry mechanism
   - Adjust timeouts in docker-compose.yml:
   ```yaml
   app:
     # ... other settings
     environment:
       - HTTP_TIMEOUT=300  # seconds
   ```