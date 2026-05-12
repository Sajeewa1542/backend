import os
import tempfile
import unittest
from unittest.mock import patch

import backend.rate_source_extractor as extractor_module
from backend.pdf_utils import PDFGenerator
from backend.rate_resolver import RateResolver
from backend.storage_manager import StorageManager
from backend.variation_evaluator import VariationEvaluator


class TestVariationServices(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = StorageManager(data_dir=self.temp_dir.name)
        self.project = self.storage.create_project("Test Project", boq_filename="boq.csv", rate_breakdown_filename="rates.csv", schedule_filename="schedule.csv")
        self.project_id = self.project["id"]
        self.storage.add_boq_items(self.project_id, [
            {"item_number": "6.03", "description": "Concrete work", "unit": "m3", "quantity": 100.0, "rate": 5000.0, "amount": 500000.0},
            {"item_number": "RB/18", "description": "Ceramic tiles", "unit": "m2", "quantity": 10.0, "rate": 2500.0, "amount": 25000.0},
            {"item_number": "RB/19", "description": "Polished granite floor slabs", "unit": "m2", "quantity": 10.0, "rate": 9300.0, "amount": 93000.0},
            {"item_number": "A101", "description": "Additional item", "unit": "nr", "quantity": 0.0, "rate": 1500.0, "amount": 0.0},
        ])
        self.storage.add_activities(self.project_id, [
            {"activity_id": "A1", "name": "Start", "duration": 5.0, "predecessors": None},
            {"activity_id": "A2", "name": "Non critical work", "duration": 5.0, "predecessors": "A1"},
            {"activity_id": "A3", "name": "Critical work", "duration": 15.0, "predecessors": "A1"},
        ])
        self.evaluator = VariationEvaluator(self.storage)
        self.resolver = RateResolver(self.storage)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_type1_quantity_increase_uses_rate(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "original_boq_item_ref": "6.03",
            "original_quantity": 100.0,
            "new_quantity": 130.0,
            "confirmed_rate": 5000.0,
            "confirmed_rate_source": "BOQ",
            "human_confirmed": True,
        })
        self.assertAlmostEqual(result["total_cost_impact"], 150000.0)
        self.assertEqual(result["cost_lines"][0]["line_type"], "quantity_change")

    def test_type1_quantity_reduction_is_negative(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "original_boq_item_ref": "6.03",
            "original_quantity": 100.0,
            "new_quantity": 80.0,
            "confirmed_rate": 5000.0,
            "confirmed_rate_source": "BOQ",
            "human_confirmed": True,
        })
        self.assertAlmostEqual(result["total_cost_impact"], -100000.0)

    def test_type4_omission(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE4",
            "evaluation_mode": "omission",
            "original_boq_item_ref": "6.03",
            "original_quantity": 50.0,
            "confirmed_rate": 5000.0,
            "confirmed_rate_source": "BOQ",
            "human_confirmed": True,
        })
        self.assertAlmostEqual(result["total_cost_impact"], -250000.0)
        self.assertLess(result["cost_lines"][0]["amount"], 0)

    def test_type2_substitution_ceramic_to_granite(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE2",
            "evaluation_mode": "substitution",
            "original_boq_item_ref": "RB/18",
            "replacement_item_ref": "RB/19",
            "original_quantity": 10.0,
            "replacement_quantity": 10.0,
            "confirmed_rate": 9300.0,
            "confirmed_rate_source": "BOQ",
            "human_confirmed": True,
        })
        self.assertAlmostEqual(result["total_cost_impact"], 68000.0)
        self.assertEqual(len(result["cost_lines"]), 2)

    def test_type5_additional_work(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE5",
            "evaluation_mode": "additional_work",
            "replacement_item_ref": "A101",
            "new_quantity": 12.0,
            "confirmed_rate": 1500.0,
            "confirmed_rate_source": "BOQ",
            "human_confirmed": True,
        })
        self.assertAlmostEqual(result["total_cost_impact"], 18000.0)

    def test_missing_rate_source_returns_manual_required(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "original_boq_item_ref": "6.03",
            "original_quantity": 100.0,
            "new_quantity": 130.0,
            "human_confirmed": True,
        })
        self.assertTrue(result["manual_confirmation_required"])
        self.assertEqual(result["cost_lines"], [])

    def test_rate_source_extractor_creates_candidates_from_pdf_text(self):
        class FakePage:
            def __init__(self, text):
                self._text = text

            def extract_text(self):
                return self._text

        class FakePdfReader:
            def __init__(self, _path):
                self.pages = [
                    FakePage("BSR/19 Polished granite floor slabs m2 9300"),
                    FakePage("BSR/20 Cement screed m2 1800"),
                ]

        with patch.object(extractor_module, "PdfReader", FakePdfReader):
            extracted = extractor_module.rate_source_extractor.extract_from_file("dummy.pdf", "bsr", source_file="dummy.pdf")

        self.assertGreaterEqual(len(extracted), 2)
        stored = self.storage.add_rate_sources(self.project_id, extracted)
        self.assertEqual(stored, len(extracted))
        self.assertGreaterEqual(len(self.storage.get_rate_sources(self.project_id)), 2)

    def test_critical_activity_delay_creates_eot(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "original_boq_item_ref": "6.03",
            "original_quantity": 100.0,
            "new_quantity": 120.0,
            "confirmed_rate": 5000.0,
            "confirmed_rate_source": "BOQ",
            "confirmed_activity_ref": "A3",
            "confirmed_productivity": 5.0,
            "productivity_source": "work study",
            "human_confirmed": True,
        })
        self.assertGreater(result["time_impact"]["eot_days"], 0)
        self.assertTrue(result["time_impact"]["is_critical"])

    def test_noncritical_delay_absorbed_by_float(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "original_boq_item_ref": "6.03",
            "original_quantity": 100.0,
            "new_quantity": 104.0,
            "confirmed_rate": 5000.0,
            "confirmed_rate_source": "BOQ",
            "confirmed_activity_ref": "A2",
            "confirmed_productivity": 1.0,
            "productivity_source": "work study",
            "human_confirmed": True,
        })
        self.assertEqual(result["time_impact"]["eot_days"], 0.0)
        self.assertTrue(result["time_impact"]["delay_absorbed_by_float"])

    def test_noncritical_delay_exceeding_float_creates_partial_eot(self):
        result = self.evaluator.evaluate_confirmed_variation(self.project_id, {
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "original_boq_item_ref": "6.03",
            "original_quantity": 100.0,
            "new_quantity": 112.0,
            "confirmed_rate": 5000.0,
            "confirmed_rate_source": "BOQ",
            "confirmed_activity_ref": "A2",
            "confirmed_productivity": 1.0,
            "productivity_source": "work study",
            "human_confirmed": True,
        })
        self.assertGreater(result["time_impact"]["eot_days"], 0.0)
        self.assertFalse(result["time_impact"]["delay_absorbed_by_float"])

    def test_pdf_generation_returns_valid_file(self):
        output_path = os.path.join(self.temp_dir.name, "proposal.pdf")
        pdf_path = PDFGenerator.generate_variation_proposal({
            "variation_id": 1,
            "variation_type": "TYPE1",
            "evaluation_mode": "quantity_change",
            "human_confirmed": True,
            "cost_lines": [{"line_type": "quantity_change", "description": "Concrete work", "quantity": 30, "unit": "m3", "rate": 5000, "rate_source": "BOQ", "rate_source_id": "6.03", "formula": "(130 - 100) x 5000", "amount": 150000}],
            "total_cost_impact": 150000,
            "time_impact": {"activity_name": "Critical work", "additional_duration": 4, "is_critical": True, "original_float": 0, "baseline_project_duration": 20, "revised_project_duration": 24, "eot_days": 4, "formula": "4 / 1"},
            "validation": {"valid": True, "warnings": [], "errors": []},
            "rate_sources": [],
            "uploaded_documents": [],
        }, output_path)
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 0)

    def test_human_confirmed_false_rejects_evaluation(self):
        with self.assertRaises(ValueError):
            self.evaluator.evaluate_confirmed_variation(self.project_id, {
                "variation_type": "TYPE1",
                "evaluation_mode": "quantity_change",
                "original_boq_item_ref": "6.03",
                "original_quantity": 100.0,
                "new_quantity": 130.0,
                "confirmed_rate": 5000.0,
                "confirmed_rate_source": "BOQ",
                "human_confirmed": False,
            })


if __name__ == "__main__":
    unittest.main()