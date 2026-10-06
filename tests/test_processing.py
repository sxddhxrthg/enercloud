"""Unit tests for ENERCloud processing logic.
Run from project root:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda", "ingest"))
from processing import (compute_power_kw, compute_baseline, detect_anomaly,  # noqa: E402
                        process_reading, validate_reading)


def reading(**overrides):
    base = {"building_id": "LAB-1", "sensor_id": "SEN-LAB-1-01", "voltage": 230.0, "current": 13.0}
    base.update(overrides)
    return base


class TestValidation(unittest.TestCase):
    def test_valid_reading(self):
        clean, errors = validate_reading(reading())
        self.assertEqual(errors, [])
        self.assertEqual(clean["building_id"], "LAB-1")

    def test_unknown_building(self):
        _, errors = validate_reading(reading(building_id="MOON-BASE"))
        self.assertTrue(any("Unknown building_id" in e for e in errors))

    def test_sensor_not_registered_to_building(self):
        _, errors = validate_reading(reading(sensor_id="SEN-LIB-01"))
        self.assertTrue(any("not registered" in e for e in errors))

    def test_voltage_out_of_range(self):
        _, errors = validate_reading(reading(voltage=400))
        self.assertTrue(any("voltage" in e for e in errors))

    def test_non_numeric_current(self):
        _, errors = validate_reading(reading(current="lots"))
        self.assertTrue(any("current must be a number" in e for e in errors))

    def test_boolean_rejected(self):
        _, errors = validate_reading(reading(current=True))
        self.assertTrue(errors)

    def test_non_object_body(self):
        _, errors = validate_reading(["not", "a", "dict"])
        self.assertEqual(errors, ["Body must be a JSON object"])


class TestPower(unittest.TestCase):
    def test_power_formula(self):
        # 230 V x 18.2 A = 4186 W = 4.186 kW
        self.assertEqual(compute_power_kw(230.0, 18.2), 4.186)


class TestAnomaly(unittest.TestCase):
    NORMAL_HISTORY = [3.0, 3.1, 2.9, 3.0, 3.2, 2.8]   # avg ~3.0 kW

    def test_normal_reading(self):
        result = detect_anomaly("LAB-1", 3.2, self.NORMAL_HISTORY)
        self.assertEqual(result["status"], "NORMAL")

    def test_rule1_threshold(self):
        # 6.5 kW > LAB-1 max 6.0 kW, no history needed
        result = detect_anomaly("LAB-1", 6.5, [])
        self.assertEqual(result["status"], "ANOMALY")
        self.assertTrue(result["reasons"][0].startswith("THRESHOLD"))

    def test_rule2_deviation_below_threshold(self):
        # 5.0 kW is under the 6.0 limit but > 1.5 x 3.0 baseline
        result = detect_anomaly("LAB-1", 5.0, self.NORMAL_HISTORY)
        self.assertEqual(result["status"], "ANOMALY")
        self.assertTrue(any(r.startswith("DEVIATION") for r in result["reasons"]))

    def test_rule2_needs_min_samples(self):
        # Only 3 samples: baseline unavailable, 5.0 kW passes Rule 2
        self.assertIsNone(compute_baseline([3.0, 3.0, 3.0]))
        self.assertEqual(detect_anomaly("LAB-1", 5.0, [3.0, 3.0, 3.0])["status"], "NORMAL")

    def test_both_rules(self):
        result = detect_anomaly("LAB-1", 8.9, self.NORMAL_HISTORY)
        self.assertEqual(len(result["reasons"]), 2)

    def test_full_pipeline(self):
        record, errors = process_reading(reading(current=38.7), self.NORMAL_HISTORY)  # ~8.9 kW
        self.assertEqual(errors, [])
        self.assertEqual(record["status"], "ANOMALY")
        self.assertAlmostEqual(record["power_kw"], 8.901, places=3)


if __name__ == "__main__":
    unittest.main()
