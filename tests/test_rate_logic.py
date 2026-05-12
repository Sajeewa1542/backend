import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.engine import CostEngine
from backend.database import SessionLocal, Project, BOQItem, init_db
import unittest

class TestRateLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("Starting setUpClass...")
        init_db()
        print("DB initialized.")
        cls.db = SessionLocal()
        # Create a dummy project
        cls.project = Project(name="Test Project", accepted_contract_amount=1000000.0) # 1 Million
        cls.db.add(cls.project)
        cls.db.commit()
        cls.db.refresh(cls.project)
        print(f"Project created with ID: {cls.project.id}")
        
        # Add a BOQ item
        cls.item = BOQItem(
            project_id=cls.project.id,
            description="Concrete Grade 30",
            quantity=100.0,
            rate=5000.0,
            amount=500000.0,
            is_fixed_rate=0
        )
        cls.db.add(cls.item)
        cls.db.commit()
        cls.db.refresh(cls.item)
        
        cls.engine = CostEngine(cls.db)

    def test_rate_change_thresholds(self):
        # Rule a: > 10% change in quantity (11 units)
        # Rule b: (change * rate) > 0.01% of Contract Amount (0.01% of 1M = 100)
        # 11 * 5000 = 55000 (> 100) - PASS
        # Rule c: Unit cost change > 1% (Passed as 1.1) - PASS
        # Rule d: Not fixed - PASS
        
        item_dict = {
            'id': self.item.id,
            'project_id': self.project.id,
            'description': self.item.description,
            'quantity': self.item.quantity,
            'rate': self.item.rate,
            'is_fixed_rate': self.item.is_fixed_rate
        }
        
        # Test 1: Should trigger new rate (passing unit_cost_change_pct > 1)
        new_rate = self.engine.calculate_new_rate(item_dict, qty_change=11.0, unit_cost_change_pct=1.5)
        # It calls derive_star_rate. Since no other items, it might return 0 or original if similarity search fails.
        # But for the purpose of threshold check, it shouldn't be original_rate if all conditions met.
        self.assertNotEqual(new_rate, 5000.0)
        
        # Test 2: Qty change < 10% (say 5 units)
        new_rate_small_qty = self.engine.calculate_new_rate(item_dict, qty_change=5.0, unit_cost_change_pct=1.5)
        self.assertEqual(new_rate_small_qty, 5000.0)
        
        # Test 3: Value change < 0.01% (Contract Amount is huge)
        self.project.accepted_contract_amount = 1000000000.0 # 1 Billion
        self.db.commit()
        # 11 * 5000 = 55000. 0.01% of 1B = 100000. 55000 < 100000.
        new_rate_high_threshold = self.engine.calculate_new_rate(item_dict, qty_change=11.0, unit_cost_change_pct=1.5)
        self.assertEqual(new_rate_high_threshold, 5000.0)

    @classmethod
    def tearDownClass(cls):
        cls.db.delete(cls.item)
        cls.db.delete(cls.project)
        cls.db.commit()
        cls.db.close()

if __name__ == "__main__":
    unittest.main()
