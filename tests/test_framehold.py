import copy
import threading
import unittest
from contextlib import contextmanager

from framehold_core import Controller, HIGH_PERFORMANCE, TweakError, validate_snapshot

BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
OWNER = "S-1-5-21-test"


class FakeBackend:
    def __init__(self):
        self.mode = {"exists": False, "value": None, "kind": None}
        self.plan = BALANCED
        self.available = True
        self.fail_plan = False
        self.fail_restore_plan = False
        self.fail_remove_mode = False
        self.checked = 0
        self.capture = [{"exists": False, "value": None, "kind": None} for _ in range(2)]
        self.gpu = {"exists": False, "value": None, "kind": None}
        self.game_path = r"C:\Games\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe"
        self.created = set()
        self.fail_capture_second = False

    def check_account(self):
        self.checked += 1

    def get_game_mode(self):
        return self.mode.copy()

    def set_game_mode(self, value):
        self.mode = {"exists": True, "value": value, "kind": "dword"}

    def remove_game_mode(self):
        if self.fail_remove_mode:
            raise OSError("mode restore denied")
        self.mode = {"exists": False, "value": None, "kind": None}

    def get_active_plan(self):
        return self.plan

    def has_plan(self, guid):
        return (self.available and guid == HIGH_PERFORMANCE) or guid in self.created

    def new_guid(self):
        return "b71addf2-3e60-42c4-913f-fb31f0e61742"

    def create_high_performance_plan(self, guid):
        self.created.add(guid)

    def delete_plan(self, guid):
        self.created.remove(guid)

    def get_capture(self):
        return copy.deepcopy(self.capture)

    def set_capture_one(self, index, value):
        if index == 1 and value == 0 and self.fail_capture_second:
            self.fail_capture_second = False
            raise OSError("capture write denied")
        self.capture[index] = {"exists": True, "value": value, "kind": "dword"}

    def set_capture(self, value):
        for index in range(2):
            self.set_capture_one(index, value)

    def remove_capture_one(self, index):
        self.capture[index] = {"exists": False, "value": None, "kind": None}

    def resolve_game_exe(self, supplied):
        return supplied or self.game_path

    def get_gpu(self, path):
        return self.gpu.copy()

    def high_performance_gpu_value(self, current):
        return "GpuPreference=2;"

    def set_gpu(self, path, value):
        self.gpu = {"exists": True, "value": value, "kind": "string"}

    def remove_gpu(self, path):
        self.gpu = {"exists": False, "value": None, "kind": None}

    def set_active_plan(self, guid):
        if self.fail_plan and guid == HIGH_PERFORMANCE:
            raise OSError("plan apply denied")
        if self.fail_restore_plan and guid == BALANCED:
            raise OSError("plan restore denied")
        self.plan = guid

    def find_game(self):
        return []


class MemoryStore:
    owner_sid = OWNER

    def __init__(self):
        self.state = None
        self.guard = threading.Lock()
        self.legacy = False

    @contextmanager
    def lock(self):
        with self.guard:
            yield

    def read(self):
        if self.state is not None:
            return validate_snapshot(copy.deepcopy(self.state), OWNER)
        return None

    def save_new(self, data):
        if self.state is not None:
            raise TweakError("snapshot already exists")
        self.state = copy.deepcopy(data)

    def clear(self):
        self.state = None

    def legacy_pending(self):
        return self.legacy


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.store = MemoryStore()
        self.controller = Controller(self.backend, self.store)

    def test_balanced_round_trip(self):
        self.controller.apply("balanced")
        self.assertEqual(self.backend.mode["value"], 1)
        self.assertEqual(self.backend.plan, BALANCED)
        self.assertIsNotNone(self.store.read())
        self.controller.restore()
        self.assertFalse(self.backend.mode["exists"])
        self.assertIsNone(self.store.read())

    def test_competitive_round_trip(self):
        self.controller.apply("competitive")
        self.assertEqual(self.backend.plan, HIGH_PERFORMANCE)
        self.controller.restore()
        self.assertEqual(self.backend.plan, BALANCED)

    def test_unavailable_plan_is_skipped(self):
        self.backend.available = False
        self.controller.apply("competitive")
        self.assertNotEqual(self.backend.plan, BALANCED)
        self.assertTrue(self.store.read()["power_plan"]["created"])
        self.controller.restore()
        self.assertEqual(self.backend.plan, BALANCED)
        self.assertEqual(self.backend.created, set())

    def test_capture_and_gpu_round_trip(self):
        self.backend.capture[0] = {"exists": True, "value": 1, "kind": "dword"}
        self.backend.gpu = {"exists": True, "value": "Other=4;", "kind": "string"}
        self.controller.apply("competitive", {"capture", "gpu"})
        self.assertEqual([x["value"] for x in self.backend.capture], [0, 0])
        self.assertEqual(self.backend.gpu["value"], "GpuPreference=2;")
        self.controller.restore()
        self.assertEqual(self.backend.capture[0]["value"], 1)
        self.assertFalse(self.backend.capture[1]["exists"])
        self.assertEqual(self.backend.gpu["value"], "Other=4;")

    def test_partial_capture_failure_rolls_back(self):
        self.backend.fail_capture_second = True
        with self.assertRaisesRegex(TweakError, "original settings restored"):
            self.controller.apply("balanced")
        self.assertFalse(self.backend.mode["exists"])
        self.assertFalse(any(x["exists"] for x in self.backend.capture))
        self.assertIsNone(self.store.read())

    def test_gpu_external_change_kept(self):
        self.controller.apply("competitive", {"gpu"})
        self.backend.gpu = {"exists": True, "value": "GpuPreference=1;", "kind": "string"}
        self.controller.restore()
        self.assertEqual(self.backend.gpu["value"], "GpuPreference=1;")

    def test_previous_snapshot_schema_still_restores(self):
        self.store.state = {
            "schema": 1, "owner_sid": OWNER, "preset": "competitive",
            "game_mode": {"changed": True, "exists": False, "value": None, "kind": None, "applied": 1},
            "power_plan": {"changed": True, "original": BALANCED, "applied": HIGH_PERFORMANCE},
        }
        self.backend.set_game_mode(1)
        self.backend.plan = HIGH_PERFORMANCE
        self.controller.restore()
        self.assertFalse(self.backend.mode["exists"])
        self.assertEqual(self.backend.plan, BALANCED)

    def test_invalid_feature_does_not_save_state(self):
        with self.assertRaisesRegex(TweakError, "supported controls"):
            self.controller.apply("competitive", {"render-scale"})
        self.assertIsNone(self.store.read())

    def test_apply_failure_rolls_back(self):
        self.backend.fail_plan = True
        with self.assertRaisesRegex(TweakError, "original settings restored"):
            self.controller.apply("competitive")
        self.assertFalse(self.backend.mode["exists"])
        self.assertIsNone(self.store.read())

    def test_restore_failure_keeps_snapshot(self):
        self.controller.apply("competitive")
        self.backend.fail_restore_plan = True
        with self.assertRaisesRegex(TweakError, "saved state kept"):
            self.controller.restore()
        self.assertIsNotNone(self.store.read())
        self.backend.fail_restore_plan = False
        self.controller.restore()
        self.assertIsNone(self.store.read())

    def test_apply_and_rollback_failures_are_reported(self):
        self.backend.fail_plan = True
        self.backend.fail_remove_mode = True
        with self.assertRaisesRegex(TweakError, "apply failed:.*restore failed:.*saved state kept"):
            self.controller.apply("competitive")
        self.assertIsNotNone(self.store.read())

    def test_external_changes_are_kept(self):
        self.controller.apply("competitive")
        self.backend.mode = {"exists": True, "value": 0, "kind": "dword"}
        self.backend.plan = "4a019a6e-d847-49ba-9709-ff5cd1cbb9c2"
        messages = self.controller.restore()
        self.assertEqual(self.backend.mode["value"], 0)
        self.assertNotEqual(self.backend.plan, BALANCED)
        self.assertTrue(any("elsewhere" in message for message in messages))

    def test_corrupt_snapshot_blocks_changes(self):
        self.store.state = {"schema": 1}
        with self.assertRaises(TweakError):
            self.controller.apply("balanced")
        with self.assertRaises(TweakError):
            self.controller.restore()

    def test_unexpected_registry_type_blocks_changes(self):
        self.backend.mode = {"exists": True, "value": "1", "kind": "other"}
        with self.assertRaisesRegex(TweakError, "unexpected registry type"):
            self.controller.apply("balanced")

    def test_two_simultaneous_applies_keep_first_snapshot(self):
        outcomes = []
        def run():
            try:
                outcomes.append(("ok", self.controller.apply("balanced")))
            except TweakError as error:
                outcomes.append(("error", str(error)))
        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start(); second.start(); first.join(); second.join()
        self.assertEqual(sum(kind == "ok" for kind, _ in outcomes), 1)
        self.assertEqual(sum(kind == "error" for kind, _ in outcomes), 1)
        self.assertIsNotNone(self.store.read())

    def test_legacy_state_blocks_new_apply(self):
        self.store.legacy = True
        with self.assertRaisesRegex(TweakError, "previous version"):
            self.controller.apply("balanced")

    def test_legacy_state_blocks_restore_without_import(self):
        self.store.legacy = True
        with self.assertRaisesRegex(TweakError, "previous version"):
            self.controller.restore()
        self.assertIsNone(self.store.read())


if __name__ == "__main__":
    unittest.main()
