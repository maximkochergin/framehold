import unittest

from framehold_audit import _driver_age_days, analyze_inventory


class AuditTests(unittest.TestCase):
    def test_driver_age_parses_windows_and_iso_dates(self):
        self.assertGreater(_driver_age_days("2000-01-01"), 1000)
        self.assertGreater(_driver_age_days("/Date(946684800000)/"), 1000)
    def test_normal_tcp_enum_is_not_reported_as_problem(self):
        data = {"tcp": [{"SettingName": "Internet", "AutoTuningLevelLocal": 3}]}
        findings = analyze_inventory(data, {"game_mode": "on", "capture": "off"})
        self.assertFalse(any("tcp receive" in item["title"] for item in findings))

    def test_hardware_and_network_findings_are_specific(self):
        data = {
            "os": {"TotalVisibleMemorySize": 6 * 1048576, "FreePhysicalMemory": 800000},
            "disk": [{"MediaType": "HDD", "HealthStatus": "Healthy"}],
            "net": [{"Name": "Wi-Fi", "InterfaceDescription": "wireless adapter"}],
            "net_stats": [{"Name": "Wi-Fi", "ReceivedPacketErrors": 2}],
        }
        titles = [item["title"] for item in analyze_inventory(data, {"game_mode": "on", "capture": "off"})]
        self.assertIn("limited memory", titles)
        self.assertIn("hard drive detected", titles)
        self.assertIn("wireless network in use", titles)
        self.assertIn("adapter packet errors recorded", titles)


if __name__ == "__main__":
    unittest.main()
