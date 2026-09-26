import os
import tempfile
import unittest

from framehold_benchmark import analyze_csv


class BenchmarkTests(unittest.TestCase):
    def test_filters_other_applications_and_invalid_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "capture.csv")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write("Application,MsBetweenPresents,MsCPUBusy,MsGPUBusy\n")
                for _ in range(100):
                    handle.write("FortniteClient-Win64-Shipping.exe,10,3,5\n")
                handle.write("Other.exe,100,99,99\n")
                handle.write("FortniteClient-Win64-Shipping.exe,NA,3,5\n")
            result = analyze_csv(path)
            self.assertEqual(result["frames"], 100)
            self.assertAlmostEqual(result["average_fps"], 100)
            self.assertAlmostEqual(result["p99_ms"], 10)
            self.assertAlmostEqual(result["cpu_busy_ms"], 3)

    def test_too_few_frames_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "capture.csv")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write("MsBetweenPresents\n16\n")
            with self.assertRaisesRegex(ValueError, "100 valid"):
                analyze_csv(path)


if __name__ == "__main__":
    unittest.main()
