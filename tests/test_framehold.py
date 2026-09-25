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
        return self.available

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
        self.assertEqual(self.backend.plan, BALANCED)
        self.assertFalse(self.store.read()["power_plan"]["changed"])

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
