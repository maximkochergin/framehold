"""Small, testable state machine for framehold's reversible settings."""

from __future__ import annotations

import re

VERSION = "0.2.1"
HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class TweakError(RuntimeError):
    pass


def valid_guid(value: object) -> bool:
    return isinstance(value, str) and GUID.fullmatch(value.lower()) is not None


def validate_snapshot(data: object, owner_sid: str) -> dict:
    if not isinstance(data, dict) or set(data) != {"schema", "owner_sid", "preset", "game_mode", "power_plan"}:
        raise TweakError("saved state has an invalid structure")
    if type(data["schema"]) is not int or data["schema"] != 1 or data["owner_sid"] != owner_sid:
        raise TweakError("saved state belongs to another account or version")
    if data["preset"] not in ("balanced", "competitive"):
        raise TweakError("saved state has an invalid profile")
    mode = data["game_mode"]
    plan = data["power_plan"]
    if not isinstance(mode, dict) or set(mode) != {"changed", "exists", "value", "kind", "applied"}:
        raise TweakError("saved game mode state is invalid")
    if type(mode["changed"]) is not bool or type(mode["exists"]) is not bool or type(mode["applied"]) is not int or mode["applied"] != 1:
        raise TweakError("saved game mode state is invalid")
    if mode["exists"]:
        if type(mode["value"]) is not int or mode["kind"] != "dword" or mode["value"] not in (0, 1):
            raise TweakError("saved game mode value is invalid")
    elif mode["value"] is not None or mode["kind"] is not None:
        raise TweakError("saved game mode value is invalid")
    if not isinstance(plan, dict) or set(plan) != {"changed", "original", "applied"}:
        raise TweakError("saved power plan state is invalid")
    if type(plan["changed"]) is not bool or not valid_guid(plan["original"]) or plan["applied"] != HIGH_PERFORMANCE:
        raise TweakError("saved power plan state is invalid")
    return data


class Controller:
    def __init__(self, backend, store):
        self.backend = backend
        self.store = store

    def status(self) -> dict:
        mode = self.backend.get_game_mode()
        try:
            saved = "available" if self.store.read() is not None else (
                "legacy" if self.store.legacy_pending() else "none"
            )
        except TweakError:
            saved = "invalid"
        return {
            "plan": self.backend.get_active_plan(),
            "game_mode": "system default" if not mode["exists"] else (
                "unsupported" if mode["kind"] != "dword" or mode["value"] not in (0, 1)
                else ("on" if mode["value"] == 1 else "off")
            ),
            "game_running": bool(self.backend.find_game()),
            "saved_state": saved,
        }

    def preview(self, preset: str) -> list[str]:
        if preset not in ("balanced", "competitive"):
            raise TweakError("unknown profile")
        lines = ["game mode       on for the current account"]
        if preset == "competitive":
            if self.backend.has_plan(HIGH_PERFORMANCE):
                lines.append("power plan      high performance")
            else:
                lines.append("power plan      unavailable; current plan stays")
        else:
            lines.append("power plan      current plan stays")
        lines.append("game files      untouched")
        return lines

    def apply(self, preset: str) -> list[str]:
        if preset not in ("balanced", "competitive"):
            raise TweakError("unknown profile")
        with self.store.lock():
            if self.store.read() is not None:
                raise TweakError("restore the saved profile before applying another")
            if self.store.legacy_pending():
                raise TweakError("restore the previous version's saved profile first")
            self.backend.check_account()
            before_mode = self.backend.get_game_mode()
            if before_mode["exists"] and before_mode["kind"] != "dword":
                raise TweakError("game mode uses an unexpected registry type; no change made")
            if before_mode["exists"] and before_mode["value"] not in (0, 1):
                raise TweakError("game mode has an unexpected value; no change made")
            before_plan = self.backend.get_active_plan()
            if not valid_guid(before_plan):
                raise TweakError("windows returned an invalid power plan")
            change_mode = not before_mode["exists"] or before_mode["value"] != 1
            change_plan = preset == "competitive" and self.backend.has_plan(HIGH_PERFORMANCE) and before_plan != HIGH_PERFORMANCE
            if not (change_mode or change_plan):
                return ["selected settings are already active"]
            state = {
                "schema": 1,
                "owner_sid": self.store.owner_sid,
                "preset": preset,
                "game_mode": {"changed": change_mode, "exists": before_mode["exists"], "value": before_mode["value"], "kind": before_mode["kind"], "applied": 1},
                "power_plan": {"changed": change_plan, "original": before_plan, "applied": HIGH_PERFORMANCE},
            }
            self.store.save_new(state)
            try:
                if change_mode:
                    self.backend.set_game_mode(1)
                if change_plan:
                    self.backend.set_active_plan(HIGH_PERFORMANCE)
            except Exception as apply_error:
                try:
                    self._restore_locked()
                except Exception as restore_error:
                    raise TweakError(f"apply failed: {apply_error}; restore failed: {restore_error}; saved state kept") from apply_error
                raise TweakError(f"apply failed: {apply_error}; original settings restored") from apply_error
            return [f"{preset} profile applied", "use restore to return to saved settings"]

    def restore(self) -> list[str]:
        with self.store.lock():
            self.backend.check_account()
            if self.store.read() is None and self.store.legacy_pending():
                raise TweakError("restore the previous version's saved profile first")
            return self._restore_locked()

    def _restore_locked(self) -> list[str]:
        state = self.store.read()
        if state is None:
            return ["there is no saved profile"]
        messages = []
        errors = []
        mode = state["game_mode"]
        if mode["changed"]:
            try:
                current = self.backend.get_game_mode()
                if current["exists"] and current["kind"] == "dword" and current["value"] == mode["applied"]:
                    if mode["exists"]:
                        self.backend.set_game_mode(mode["value"])
                    else:
                        self.backend.remove_game_mode()
                    messages.append("game mode restored")
                else:
                    messages.append("game mode changed elsewhere; current value kept")
            except Exception as error:
                errors.append(f"game mode: {error}")
        plan = state["power_plan"]
        if plan["changed"]:
            try:
                current = self.backend.get_active_plan()
                if current == plan["applied"]:
                    self.backend.set_active_plan(plan["original"])
                    messages.append("power plan restored")
                else:
                    messages.append("power plan changed elsewhere; current value kept")
            except Exception as error:
                errors.append(f"power plan: {error}")
        if errors:
            raise TweakError("restore incomplete: " + "; ".join(errors) + "; saved state kept")
        self.store.clear()
        messages.append("restore complete")
        return messages
