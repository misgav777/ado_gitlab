from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime

Base = declarative_base()

class MigrationState(Base):
    __tablename__ = 'migration_state'
    
    id = Column(Integer, primary_key=True)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(50), default='in_progress')  # in_progress, completed, failed
    total_items = Column(Integer, default=0)
    processed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    
def get_session(db_url):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

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
