# Database Integration Documentation

This document explains the database components used in the ADO to GitLab migration tool for tracking migration state and maintaining mappings between systems.

## Database Models (`db_models.py`)

The database models define the schema for tracking migration state and mapping entities between Azure DevOps and GitLab.

### Core Components

#### 1. Base Configuration

```python
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime

Base = declarative_base()
```

#### 2. MigrationState Model

Tracks the overall state of a migration run:

```python
class MigrationState(Base):
    __tablename__ = 'migration_state'
    
    id = Column(Integer, primary_key=True)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(50), default='in_progress')  # in_progress, completed, failed
    total_items = Column(Integer, default=0)
    processed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
```

#### 3. WorkItemMapping Model

Maps Azure DevOps work items to GitLab issues/epics:

```python
class WorkItemMapping(Base):
    __tablename__ = 'work_item_mappings'
    
    id = Column(Integer, primary_key=True)
    ado_id = Column(Integer, nullable=False, index=True)
    ado_type = Column(String(100), nullable=False)
    gitlab_id = Column(Integer, nullable=False, index=True)
    gitlab_type = Column(String(100), nullable=False) # issue or epic
    migration_state_id = Column(Integer, ForeignKey('migration_state.id'))
    processed_at = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String(50), default='success')  # success, failed
    error_message = Column(Text, nullable=True)
    
    migration_state = relationship("MigrationState")
```

#### 4. RelationshipMapping Model

Tracks relationships between work items that need to be processed:

```python
class RelationshipMapping(Base):
    __tablename__ = 'relationship_mappings'
    
    id = Column(Integer, primary_key=True)
    source_ado_id = Column(Integer, nullable=False, index=True)
    target_ado_id = Column(Integer, nullable=False, index=True)
    relationship_type = Column(String(100), nullable=False)  # parent, child, related, etc.
    migration_state_id = Column(Integer, ForeignKey('migration_state.id'))
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=True)  # success, failed
    error_message = Column(Text, nullable=True)
    
    migration_state = relationship("MigrationState")
```

#### 5. Session Creation

```python
def get_session(db_url):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
```

## Database Handler (`db_handler.py`)

The DatabaseHandler class provides an interface for interacting with the database.

### Core Methods

#### 1. Initialization

```python
class DatabaseHandler:
    def __init__(self, db_url):
        self.db_url = db_url
        self.session = get_session(db_url)
        self.current_migration = None
```

#### 2. Migration Management

```python
def start_migration(self, total_items=0):
    """Start a new migration and set it as current"""
    migration = MigrationState(total_items=total_items)
    self.session.add(migration)
    self.session.commit()
    self.current_migration = migration
    return migration.id

def update_migration_status(self, status, processed=None, failed=None):
    """Update the current migration status"""
    if not self.current_migration:
        return False
        
    if status == 'completed' or status == 'failed':
        self.current_migration.end_time = datetime.datetime.utcnow()
        
    self.current_migration.status = status
    
    if processed is not None:
        self.current_migration.processed_items = processed
        
    if failed is not None:
        self.current_migration.failed_items = failed
        
    self.session.commit()
    return True
```

#### 3. Work Item Mapping

```python
def add_work_item_mapping(self, ado_id, ado_type, gitlab_id, gitlab_type, status='success', error_message=None):
    """Add a mapping between ADO and GitLab work items"""
    if not self.current_migration:
        return False
        
    mapping = WorkItemMapping(
        ado_id=ado_id,
        ado_type=ado_type,
        gitlab_id=gitlab_id,
        gitlab_type=gitlab_type,
        migration_state_id=self.current_migration.id,
        status=status,
        error_message=error_message
    )
    self.session.add(mapping)
    self.session.commit()
    return mapping.id

def get_gitlab_id_from_ado_id(self, ado_id):
    """Get GitLab ID from ADO ID"""
    try:
        mapping = self.session.query(WorkItemMapping).filter_by(ado_id=ado_id).one()
        return mapping.gitlab_id, mapping.gitlab_type
    except NoResultFound:
        return None, None
```

#### 4. Relationship Management

```python
def add_relationship(self, source_ado_id, target_ado_id, relationship_type):
    """Add a relationship between two work items to be processed later"""
    if not self.current_migration:
        return False
        
    relationship = RelationshipMapping(
        source_ado_id=source_ado_id,
        target_ado_id=target_ado_id,
        relationship_type=relationship_type,
        migration_state_id=self.current_migration.id
    )
    self.session.add(relationship)
    self.session.commit()
    return relationship.id

def get_pending_relationships(self, limit=100):
    """Get pending relationships to be processed"""
    if not self.current_migration:
        return []
        
    return self.session.query(RelationshipMapping)\
        .filter_by(migration_state_id=self.current_migration.id, processed=False)\
        .limit(limit).all()

def update_relationship_status(self, relationship_id, status, error_message=None):
    """Update the status of a relationship"""
    relationship = self.session.query(RelationshipMapping).get(relationship_id)
    if relationship:
        relationship.processed = True
        relationship.processed_at = datetime.datetime.utcnow()
        relationship.status = status
        relationship.error_message = error_message
        self.session.commit()
        return True
    return False
```

#### 5. Statistics and Session Management

```python
def get_work_item_stats(self):
    """Get statistics about work items in the current migration"""
    if not self.current_migration:
        return {}
        
    total = self.session.query(WorkItemMapping)\
        .filter_by(migration_state_id=self.current_migration.id).count()
    
    success = self.session.query(WorkItemMapping)\
        .filter_by(migration_state_id=self.current_migration.id, status='success').count()
        
    failed = self.session.query(WorkItemMapping)\
        .filter_by(migration_state_id=self.current_migration.id, status='failed').count()
        
    return {
        'total': total,
        'success': success,
        'failed': failed
    }

def close(self):
    """Close the database session"""
    self.session.close()
    
@contextmanager
def session_scope(self):
    """Provide a transactional scope around a series of operations"""
    session = get_session(self.db_url)
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
```

## Integration with Main Migration Process

The database integration is used throughout the migration process to:

1. **Track overall migration progress**:
   - Record start/end times
   - Monitor item counts and success rates

2. **Maintain work item mappings**:
   - Store ADO to GitLab ID mappings
   - Track work item status and any errors

3. **Process relationships in phases**:
   - Record relationships during initial discovery
   - Process relationships in a separate phase
   - Track relationship status for verification

4. **Enable resumable migrations**:
   - If a migration is interrupted, it can be resumed
   - Previously migrated items can be skipped
   - Failed items can be retried

## Database Configuration

The database connection is configured in `config.py`:

```python
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

This allows for flexible deployment with either PostgreSQL (recommended for production) or SQLite (for testing).