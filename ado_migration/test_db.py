#!/usr/bin/env python3
import os
import sys
import shutil
import time
from db_handler import DatabaseHandler
from db_models import MigrationState, WorkItemMapping, RelationshipMapping

def main():
    print("Testing database integration...")
    
    # Determine if we're running in Docker
    if os.environ.get('DB_HOST') == 'db':
        print("Detected Docker environment, using PostgreSQL")
        # Use environment variables for PostgreSQL connection
        db_user = os.environ.get('DB_USER', 'postgres')
        db_password = os.environ.get('DB_PASSWORD', 'migration_password')
        db_name = os.environ.get('DB_NAME', 'ado_gitlab_migration')
        db_host = os.environ.get('DB_HOST', 'db')
        db_port = os.environ.get('DB_PORT', '5432')
        
        db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        print(f"Using PostgreSQL connection: {db_host}:{db_port}/{db_name}")
        
        # PostgreSQL might need a moment to be ready
        max_retries = 5
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                db = DatabaseHandler(db_url)
                print("✅ Database connection established")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Retrying connection in {retry_delay} seconds... ({attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    print(f"❌ Failed to connect to database after {max_retries} attempts: {e}")
                    sys.exit(1)
    else:
        print("Using SQLite for local testing")
        # Use SQLite for testing
        test_db_file = "test_migration.db"
        
        # Remove existing test database if it exists
        if os.path.exists(test_db_file):
            print(f"Removing existing test database: {test_db_file}")
            os.remove(test_db_file)
        
        db_url = f"sqlite:///{test_db_file}"
        
        # Create handler
        try:
            db = DatabaseHandler(db_url)
            print("✅ Database connection established")
        except Exception as e:
            print(f"❌ Failed to connect to database: {e}")
            sys.exit(1)
    
    # Start a migration
    try:
        migration_id = db.start_migration(total_items=100)
        print(f"✅ Started migration with ID: {migration_id}")
    except Exception as e:
        print(f"❌ Failed to start migration: {e}")
        sys.exit(1)
    
    # Add a work item mapping
    try:
        mapping_id = db.add_work_item_mapping(
            ado_id=1234,
            ado_type="User Story",
            gitlab_id=42,
            gitlab_type="issue"
        )
        print(f"✅ Added work item mapping with ID: {mapping_id}")
    except Exception as e:
        print(f"❌ Failed to add work item mapping: {e}")
        sys.exit(1)
    
    # Test retrieving the mapping
    try:
        gitlab_id, gitlab_type = db.get_gitlab_id_from_ado_id(1234)
        if gitlab_id == 42 and gitlab_type == "issue":
            print(f"✅ Successfully retrieved mapping: ADO #1234 -> GitLab {gitlab_type} #{gitlab_id}")
        else:
            print(f"❌ Failed to retrieve correct mapping. Got {gitlab_type} #{gitlab_id}")
    except Exception as e:
        print(f"❌ Failed to retrieve mapping: {e}")
        sys.exit(1)
    
    # Add a relationship
    try:
        rel_id = db.add_relationship(
            source_ado_id=1234,
            target_ado_id=5678,
            relationship_type="System.LinkTypes.Hierarchy-Forward"
        )
        print(f"✅ Added relationship with ID: {rel_id}")
    except Exception as e:
        print(f"❌ Failed to add relationship: {e}")
        sys.exit(1)
    
    # Get pending relationships
    try:
        pending = db.get_pending_relationships()
        if pending and len(pending) > 0:
            print(f"✅ Found {len(pending)} pending relationships")
            
            # Update first relationship
            if db.update_relationship_status(pending[0].id, "success"):
                print(f"✅ Updated relationship status to success")
            else:
                print(f"❌ Failed to update relationship status")
        else:
            print(f"❌ Did not find expected pending relationships")
    except Exception as e:
        print(f"❌ Failed to get pending relationships: {e}")
        sys.exit(1)
    
    # Update migration status
    try:
        db.update_migration_status("in_progress", processed=42, failed=2)
        print(f"✅ Updated migration status")
    except Exception as e:
        print(f"❌ Failed to update migration status: {e}")
        sys.exit(1)
    
    # Complete migration
    try:
        db.update_migration_status("completed")
        print(f"✅ Completed migration")
    except Exception as e:
        print(f"❌ Failed to complete migration: {e}")
        sys.exit(1)
    
    # Get stats
    try:
        stats = db.get_work_item_stats()
        print(f"✅ Migration statistics: {stats}")
    except Exception as e:
        print(f"❌ Failed to get work item stats: {e}")
        sys.exit(1)
    
    print("Database integration test completed successfully!")

if __name__ == "__main__":
    main()