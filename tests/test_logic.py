import unittest
from datetime import datetime

from app.cooling import hours_text, load_spots, nearest_open
from app.engine import classify_reply
from app.heat import category, heat_index_f


class HeatIndexTests(unittest.TestCase):
    # Values from the NWS heat index chart.
    def test_matches_nws_chart(self):
        for temp, rh, expected in [(90, 50, 95), (96, 65, 121), (100, 40, 109), (86, 90, 105), (80, 40, 80)]:
            with self.subTest(temp=temp, rh=rh):
                self.assertAlmostEqual(heat_index_f(temp, rh), expected, delta=1.0)

    def test_mild_conditions_use_simple_formula(self):
        self.assertAlmostEqual(heat_index_f(70, 50), 69.0, delta=0.5)

    def test_categories(self):
        self.assertEqual(category(79)["label"], "Normal")
        self.assertEqual(category(85)["label"], "Caution")
        self.assertEqual(category(95)["label"], "Extreme caution")
        self.assertEqual(category(110)["label"], "Danger")
        self.assertEqual(category(130)["label"], "Extreme danger")


class ReplyTests(unittest.TestCase):
    def test_keypad(self):
        self.assertEqual(classify_reply("1", ""), "ok")
        self.assertEqual(classify_reply("2", ""), "help")
        self.assertEqual(classify_reply("7", ""), "unclear")

    def test_speech(self):
        self.assertEqual(classify_reply("", "Yes I'm okay"), "ok")
        self.assertEqual(classify_reply("", "no, I'm fine"), "ok")
        self.assertEqual(classify_reply("", "I need help"), "help")
        self.assertEqual(classify_reply("", "I'm not okay"), "help")
        self.assertEqual(classify_reply("", "sí"), "ok")
        self.assertEqual(classify_reply("", "no estoy bien"), "help")
        self.assertEqual(classify_reply("", "what?"), "unclear")
        self.assertEqual(classify_reply("", ""), "unclear")


class CoolingTests(unittest.TestCase):
    def setUp(self):
        self.spots = load_spots()

    def test_weekday_midday_finds_open_center(self):
        monday_noon = datetime(2026, 9, 28, 12, 0)
        spot = nearest_open(33.731, -84.403, self.spots, monday_noon)
        self.assertTrue(spot["found"])
        self.assertIn("Butler", spot["name"])
        self.assertGreater(spot["miles"], 0)

    def test_saturday_night_falls_back(self):
        saturday_night = datetime(2026, 9, 26, 20, 0)
        spot = nearest_open(33.731, -84.403, self.spots, saturday_night)
        self.assertFalse(spot["found"])
        self.assertIn("No cooling center is open", spot["say"])
        self.assertIn("9 1 1", spot["say"])

    def test_hours_text(self):
        self.assertEqual(hours_text(self.spots[0]), "Mon–Fri 11am–6pm")


if __name__ == "__main__":
    unittest.main()
