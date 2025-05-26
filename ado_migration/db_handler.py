from sqlalchemy.orm.exc import NoResultFound
from db_models import get_session, MigrationState, WorkItemMapping, RelationshipMapping
import datetime
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError

class DatabaseHandler:
    def __init__(self, db_url):
        self.db_url = db_url
        self.session = get_session(db_url)
        self.current_migration = None
    
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
        
    def update_migration_progress(self, processed_items=None, failed_items=None, total_items=None):
        """Update the progress counters for the current migration"""
        if not self.current_migration:
            return False
            
        if processed_items is not None:
            self.current_migration.processed_items = processed_items
            
        if failed_items is not None:
            self.current_migration.failed_items = failed_items
            
        if total_items is not None:
            self.current_migration.total_items = total_items
            
        self.session.commit()
        return True
    
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
        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()
