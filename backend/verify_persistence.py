import os
import json
from storage_manager import storage_manager
from engine import CostEngine, TimeEngine
from session_manager import SessionManager

def verify_storage():
    print("--- Verifying Storage Manager ---")
    # 1. Create Project
    project = storage_manager.create_project("Test Project", boq_filename="test_boq.xlsx")
    project_id = project["id"]
    print(f"Created Project ID: {project_id}")
    
    # 2. Add BOQ Items
    boq_items = [
        {"item_number": "1.1", "description": "Concrete", "unit": "m3", "quantity": 100, "rate": 500, "amount": 50000},
        {"item_number": "1.2", "description": "Steel", "unit": "kg", "quantity": 2000, "rate": 5, "amount": 10000}
    ]
    count = storage_manager.add_boq_items(project_id, boq_items, "Sheet1")
    print(f"Added {count} BOQ items.")
    
    # 3. Verify Project Data
    loaded_project = storage_manager.get_project(project_id)
    if loaded_project and len(loaded_project["boq_items"]) == 2:
        print("✓ Project retrieval successful.")
    else:
        print("✗ Project retrieval failed.")
        return

    # 4. Create Session
    sm = SessionManager(storage_manager)
    session = sm.create_session(project_id)
    session_id = session["id"]
    print(f"Created Session ID: {session_id}")
    
    # 5. Add Chat Message
    msg = sm.add_message(project_id, session_id, "user", "Hello AI")
    print(f"Added Chat Message: {msg['content']}")
    
    # 6. Verify History
    history = sm.get_conversation_history(project_id, session_id)
    if len(history) == 1:
        print("✓ Chat history retrieval successful.")
    else:
        print("✗ Chat history retrieval failed.")

    # 7. Check project index
    projects = storage_manager.get_projects()
    if any(p["id"] == project_id for p in projects):
        print("✓ Project index successful.")
    else:
        print("✗ Project index failed.")

    print("\n--- Verifying Engines ---")
    ce = CostEngine(storage_manager)
    ce.train_model(project_id)
    print("✓ CostEngine model training (with small data) attempted.")
    
    # Basic similarity check
    matches = ce.ml_model.find_similar_item("Concrete", top_n=1)
    if matches and matches[0]["description"].lower() == "concrete":
        print("✓ ML Similarity lookups (JSON-backed) successful.")
    else:
        print(f"✗ ML Similarity lookups failed. Matches: {matches}")

    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    if not os.path.exists("backend/data"):
        os.makedirs("backend/data")
    verify_storage()
