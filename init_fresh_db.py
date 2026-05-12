"""
Initialize Fresh Database
Creates a new database with the corrected schema
"""
import sys
sys.path.insert(0, 'backend')

from backend.database import init_db, SessionLocal, VariationType

print("Creating fresh database...")
init_db()

print("Database created successfully!")

# Verify variation types
db = SessionLocal()
types = db.query(VariationType).all()
print(f"\nSeeded {len(types)} FIDIC variation types:")
for t in types:
    print(f"  - {t.code}: {t.name}")

db.close()
print("\nDatabase ready for use!")
