from backend.database import engine
from sqlalchemy import text

def migrate():
    print("Starting migration...")
    with engine.connect() as conn:
        # Check if columns exist first (SQLite specific check)
        cursor = conn.execute(text("PRAGMA table_info(projects)"))
        columns = [row[1] for row in cursor]
        
        if 'boq_filename' not in columns:
            print("Adding column boq_filename...")
            conn.execute(text("ALTER TABLE projects ADD COLUMN boq_filename VARCHAR"))
        
        if 'description' not in columns:
            print("Adding column description...")
            conn.execute(text("ALTER TABLE projects ADD COLUMN description VARCHAR"))
        
        if 'accepted_contract_amount' not in columns:
            print("Adding column accepted_contract_amount...")
            conn.execute(text("ALTER TABLE projects ADD COLUMN accepted_contract_amount FLOAT DEFAULT 0.0"))
            
        # Check boq_items
        cursor = conn.execute(text("PRAGMA table_info(boq_items)"))
        boq_columns = [row[1] for row in cursor]
        if 'is_fixed_rate' not in boq_columns:
            print("Adding column is_fixed_rate to boq_items...")
            conn.execute(text("ALTER TABLE boq_items ADD COLUMN is_fixed_rate INTEGER DEFAULT 0"))

        conn.commit()
    print("Migration successful.")

if __name__ == "__main__":
    migrate()
