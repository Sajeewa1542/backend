"""
Database Migration Script
Migrates existing database to enhanced schema while preserving data
"""
from backend.database import init_db, SessionLocal, Project, ChatMessage
from sqlalchemy import inspect
import sys

def check_table_exists(engine, table_name):
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def migrate_database():
    """Perform database migration"""
    from backend.database import engine
    
    print("=" * 60)
    print("DATABASE MIGRATION - ML Variation Evaluation System")
    print("=" * 60)
    
    # Check existing tables
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    print(f"\nExisting tables: {', '.join(existing_tables)}")
    
    # Initialize database (creates new tables, doesn't drop existing ones)
    print("\nCreating new tables...")
    init_db()
    
    # Check new tables
    new_tables = inspect(engine).get_table_names()
    added_tables = set(new_tables) - set(existing_tables)
    
    if added_tables:
        print(f"✓ Added tables: {', '.join(added_tables)}")
    else:
        print("✓ All tables already exist")
    
    # Migrate existing data if needed
    db = SessionLocal()
    try:
        # Create default session for existing chat messages without session_id
        from backend.database import Session
        
        orphan_messages = db.query(ChatMessage).filter(ChatMessage.session_id == None).all()
        
        if orphan_messages:
            print(f"\nFound {len(orphan_messages)} chat messages without session")
            
            # Group by project
            project_ids = set(msg.project_id for msg in orphan_messages)
            
            for project_id in project_ids:
                # Create a default session for this project
                session = Session(
                    project_id=project_id,
                    session_key=f"migrated_session_{project_id}",
                    status="archived",
                    session_metadata={"migrated": True, "note": "Auto-created during migration"}
                )
                db.add(session)
                db.flush()
                
                # Update messages
                project_messages = [msg for msg in orphan_messages if msg.project_id == project_id]
                for msg in project_messages:
                    msg.session_id = session.id
                
                print(f"  ✓ Created session for project {project_id} ({len(project_messages)} messages)")
            
            db.commit()
            print("✓ Migration complete")
        else:
            print("\n✓ No orphan messages found")
        
        # Verify FIDIC variation types
        from backend.database import VariationType
        var_types_count = db.query(VariationType).count()
        print(f"\n✓ FIDIC Variation Types: {var_types_count} types loaded")
        
        print("\n" + "=" * 60)
        print("MIGRATION SUCCESSFUL")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Run the backend: python -m backend.main")
        print("2. Test file uploads with new schema")
        print("3. Verify session management works")
        
    except Exception as e:
        print(f"\n✗ Migration error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    migrate_database()
