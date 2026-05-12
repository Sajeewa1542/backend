import os
import sys

# Add backend to path
sys.path.append(os.getcwd())

from backend.database import engine, Base, SessionLocal, Project, BOQItem, RateBreakdown
from backend.engine import CostEngine, TimeEngine

# Setup DB
Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Cleanup
db.query(BOQItem).delete()
db.query(RateBreakdown).delete()
db.query(Project).delete()
db.commit()

# Create Project
p = Project(name="Test Project")
db.add(p)
db.commit()

# Add Data
# 1. BOQ Item: Ceramic Tiles
b1 = BOQItem(project_id=p.id, item_number="1.1", description="Supply and lay 600x600 Ceramic Tiles", unit="m2", quantity=100, rate=50.0, amount=5000.0)
db.add(b1)

# 2. Rate Breakdown: Granite (Similar to Ceramic but more expensive)
# We add this to simulate that we have data for Granite in the system (e.g. from previous project or uploaded BSR)
r1 = RateBreakdown(
     project_id=p.id, 
     item_ref="REF-001", 
     description="Supply and lay Polished Granite Slabs", 
     material_cost=120.0, 
     labor_cost=40.0, 
     plant_cost=10.0, 
     total_rate=170.0
)
db.add(r1)
db.commit()

# Init Engine
ce = CostEngine(db)
ce.train_model(p.id)

# Test 1: Small Variation (Should return original rate)
print("--- Test 1: Small Variation ---")
rate = ce.calculate_new_rate("Change Tiles", original_rate=50.0, qty_change_pct=5.0, amt_change_pct=0.005, unit_cost_change_pct=0.0)
print(f"Original: 50.0, New: {rate}")
assert rate == 50.0

# Test 2: Large Variation (Should derive Star Rate)
# We need to manually add Granite to BOQ (as if it was there) to allow similarity search to find it if we search BOQ
# OR we update derive_star_rate to search RateBreakdowns too. 
# Current implementation searches BOQ. So let's add Granite to BOQ for the sake of the test "Similarity found in BOQ"
b2 = BOQItem(project_id=p.id, item_number="1.2", description="Supply and lay Polished Granite Slabs", unit="m2", quantity=10, rate=170.0, amount=1700.0)
db.add(b2)
db.commit()
ce.train_model(p.id) # Retrain

print("\n--- Test 2: Large Variation (Granite) ---")
# Description matches Granite, so it should find b2 as similar
# Logic: triggers star rate. 
# derive_star_rate("Granite...") -> finds b2 (Granite) -> calculates adjusted rate
# b2 rate = 170.
# productivity("Granite") / productivity("Granite") = 1.
# Result should be close to 170.
new_rate = ce.calculate_new_rate(
    item_description="Supply and lay Granite", 
    original_rate=50.0, # Original was Ceramic
    qty_change_pct=20.0, 
    amt_change_pct=0.02, 
    unit_cost_change_pct=2.0
)
print(f"Original: 50.0, New (Star Rate): {new_rate}")
# 170 * 0.7 + 170 * 0.3 * 1 = 170
assert abs(new_rate - 170.0) < 1.0

# Test 3: Time Logic (CPM)
print("\n--- Test 3: Time Logic (CPM) ---")
te = TimeEngine()
# Create a simple graph manually for testing
# A(5) -> B(3) -> D(2)
# A(5) -> C(4) -> D(2)
# Path 1: A+B+D = 5+3+2 = 10
# Path 2: A+C+D = 5+4+2 = 11 (Critical Path)
te.graph.add_node("A", name="Excavation", duration=5.0)
te.graph.add_node("B", name="Foundation", duration=3.0)
te.graph.add_node("C", name="Walls", duration=4.0)
te.graph.add_node("D", name="Roof", duration=2.0)
te.graph.add_edge("A", "B")
te.graph.add_edge("B", "D")
te.graph.add_edge("A", "C")
te.graph.add_edge("C", "D")

original_duration = te.calculate_project_duration()
print(f"Original Duration: {original_duration} (Expected 11)")
assert original_duration == 11.0

# Case A: Delay Non-Critical Task B by 1 day
# Path 1 becomes 5+4+2 = 11. Still 11. Impact should be 0.
impact_a, msg_a = te.calculate_eot("Foundation", 1.0)
print(f"Delay Foundation by 1 day: Impact {impact_a}. Msg: {msg_a}")
assert impact_a == 0.0

# Case B: Delay Critical Task C by 2 days
# Path 2 becomes 5+6+2 = 13. Impact should be 2.
impact_b, msg_b = te.calculate_eot("Walls", 2.0)
print(f"Delay Walls by 2 days: Impact {impact_b}. Msg: {msg_b}")
assert impact_b == 2.0

print("\n--- Tests Passed ---")
