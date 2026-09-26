"""Small, testable state machine for framehold's reversible settings."""

from __future__ import annotations

import re

VERSION = "0.4.0"
HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class TweakError(RuntimeError):
    pass


def valid_guid(value: object) -> bool:
    return isinstance(value, str) and GUID.fullmatch(value.lower()) is not None


def validate_snapshot(data: object, owner_sid: str) -> dict:
    old_keys = {"schema", "owner_sid", "preset", "game_mode", "power_plan"}
    new_keys = old_keys | {"capture", "gpu"}
    newest_keys = new_keys | {"mmcss"}
    if not isinstance(data, dict) or set(data) not in (old_keys, new_keys, newest_keys):
        raise TweakError("saved state has an invalid structure")
    if type(data["schema"]) is not int or data["schema"] not in (1, 2, 3) or data["owner_sid"] != owner_sid:
        raise TweakError("saved state belongs to another account or version")
    if set(data) != ({1: old_keys, 2: new_keys, 3: newest_keys}[data["schema"]]):
        raise TweakError("saved state has an invalid structure")
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
    if not isinstance(plan, dict) or set(plan) != ({"changed", "original", "applied"} if data["schema"] == 1 else {"changed", "original", "applied", "created"}):
        raise TweakError("saved power plan state is invalid")
    if type(plan["changed"]) is not bool or not valid_guid(plan["original"]) or not valid_guid(plan["applied"]):
        raise TweakError("saved power plan state is invalid")
    if data["schema"] == 1 and plan["applied"] != HIGH_PERFORMANCE:
        raise TweakError("saved power plan state is invalid")
    if data["schema"] >= 2:
        if type(plan["created"]) is not bool or (plan["created"] and not plan["changed"]):
            raise TweakError("saved power plan state is invalid")
        for name in ("capture", "gpu"):
            entry = data[name]
            if not isinstance(entry, dict) or set(entry) != {"changed", "original", "applied"}:
                raise TweakError(f"saved {name} state is invalid")
            if type(entry["changed"]) is not bool:
                raise TweakError(f"saved {name} state is invalid")
        capture = data["capture"]
        if not isinstance(capture["original"], list) or len(capture["original"]) != 2:
            raise TweakError("saved capture state is invalid")
        for original in capture["original"]:
            if not isinstance(original, dict) or set(original) != {"exists", "value", "kind"}:
                raise TweakError("saved capture state is invalid")
            if type(original["exists"]) is not bool or (original["exists"] and (type(original["value"]) is not int or original["kind"] != "dword")) or (not original["exists"] and (original["value"] is not None or original["kind"] is not None)):
                raise TweakError("saved capture state is invalid")
        if capture["applied"] != 0:
            raise TweakError("saved capture state is invalid")
        gpu = data["gpu"]
        if not isinstance(gpu["original"], dict) or set(gpu["original"]) != {"path", "exists", "value", "kind"}:
            raise TweakError("saved gpu state is invalid")
        original = gpu["original"]
        if not isinstance(original["path"], str) or len(original["path"]) > 1024 or (gpu["changed"] and not original["path"]) or (original["path"] and not original["path"].lower().endswith(r"\fortnitegame\binaries\win64\fortniteclient-win64-shipping.exe")):
            raise TweakError("saved gpu state is invalid")
        if type(original["exists"]) is not bool or (original["exists"] and (not isinstance(original["value"], str) or original["kind"] != "string")) or (not original["exists"] and (original["value"] is not None or original["kind"] is not None)):
            raise TweakError("saved gpu state is invalid")
        if not isinstance(gpu["applied"], str) or len(gpu["applied"]) > 2048:
            raise TweakError("saved gpu state is invalid")
    if data["schema"] == 3:
        mmcss = data["mmcss"]
        if not isinstance(mmcss, dict) or set(mmcss) != {"changed", "original", "applied"} or type(mmcss["changed"]) is not bool or mmcss["applied"] != 10:
            raise TweakError("saved scheduler state is invalid")
        original = mmcss["original"]
        if not isinstance(original, dict) or set(original) != {"exists", "value", "kind"} or type(original["exists"]) is not bool:
            raise TweakError("saved scheduler state is invalid")
        if original["exists"] and (type(original["value"]) is not int or original["kind"] != "dword" or not 0 <= original["value"] <= 0xffffffff):
            raise TweakError("saved scheduler state is invalid")
        if not original["exists"] and (original["value"] is not None or original["kind"] is not None):
            raise TweakError("saved scheduler state is invalid")
    return data


class Controller:
    def __init__(self, backend, store):
        self.backend = backend
        self.store = store

    def status(self) -> dict:
        mode = self.backend.get_game_mode()
        capture = self.backend.get_capture()
        mmcss = self.backend.get_mmcss()
        active_plan = self.backend.get_active_plan()
        try:
            saved = "available" if self.store.read() is not None else (
                "legacy" if self.store.legacy_pending() else "none"
            )
        except TweakError:
            saved = "invalid"
        return {
            "plan": active_plan,
            "plan_name": {"381b4222-f694-41f0-9685-ff5bb260df2e": "balanced", HIGH_PERFORMANCE: "high performance"}.get(active_plan, "custom or temporary"),
            "game_mode": "system default" if not mode["exists"] else (
                "unsupported" if mode["kind"] != "dword" or mode["value"] not in (0, 1)
                else ("on" if mode["value"] == 1 else "off")
            ),
            "game_running": bool(self.backend.find_game()),
            "capture": "off" if all(x["exists"] and x["kind"] == "dword" and x["value"] == 0 for x in capture) else "on or default",
            "scheduler": "system default" if not mmcss["exists"] else (str(mmcss["value"]) + "% low priority reserve" if mmcss["kind"] == "dword" and type(mmcss["value"]) is int else "unsupported value"),
            "hags": self.backend.get_hags(),
            "saved_state": saved,
        }

    def preview(self, preset: str, features: set[str] | None = None, game_exe: str | None = None) -> list[str]:
        if preset not in ("balanced", "competitive"):
            raise TweakError("unknown profile")
        selected = self._features(preset, features)
        lines = []
        if "game-mode" in selected:
            current = self.backend.get_game_mode()
            value = "default" if not current["exists"] else str(current["value"])
            lines.append(f"game mode       {value} -> enabled for this account")
        if "capture" in selected:
            current = self.backend.get_capture()
            values = ",".join("default" if not item["exists"] else str(item["value"]) for item in current)
            lines.append(f"game capture    {values} -> background recording disabled")
        if "power" in selected:
            kind = "existing" if self.backend.has_plan(HIGH_PERFORMANCE) else "temporary copy"
            lines.append(f"power plan      {self.backend.get_active_plan()} -> high performance ({kind}; may increase heat)")
        if "gpu" in selected:
            path = self.backend.resolve_game_exe(game_exe)
            current = self.backend.get_gpu(path)
            value = "default" if not current["exists"] else str(current["value"])
            lines.append("graphics gpu    " + value.lower() + " -> high performance for " + path.lower())
        if "mmcss" in selected:
            current = self.backend.get_mmcss()
            value = "default" if not current["exists"] else str(current["value"])
            lines.append(f"cpu scheduler  {value} -> 10% low priority reserve for mmcss tasks; experimental, reboot")
        lines.append("game settings   untouched")
        return lines

    def _features(self, preset: str, features: set[str] | None) -> set[str]:
        selected = features if features is not None else ({"game-mode", "capture"} if preset == "balanced" else {"game-mode", "capture", "power"})
        if not selected or selected - {"game-mode", "capture", "power", "gpu", "mmcss"}:
            raise TweakError("select one or more supported controls")
        return selected

    def apply(self, preset: str, features: set[str] | None = None, game_exe: str | None = None, backup: bool = True) -> list[str]:
        if preset not in ("balanced", "competitive"):
            raise TweakError("unknown profile")
        selected = self._features(preset, features)
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
            capture = self.backend.get_capture()
            mmcss = self.backend.get_mmcss()
            if "mmcss" in selected and mmcss["exists"] and (mmcss["kind"] != "dword" or type(mmcss["value"]) is not int or not 0 <= mmcss["value"] <= 0xffffffff):
                raise TweakError("scheduler reserve has an unexpected value; no change made")
            if "capture" in selected and any(x["exists"] and (x["kind"] != "dword" or type(x["value"]) is not int or x["value"] not in (0, 1)) for x in capture):
                raise TweakError("game capture uses an unexpected registry value; no change made")
            game_path = self.backend.resolve_game_exe(game_exe) if "gpu" in selected else ""
            gpu = self.backend.get_gpu(game_path) if game_path else {"exists": False, "value": None, "kind": None}
            if gpu["exists"] and (gpu["kind"] != "string" or len(gpu["value"]) > 1024):
                raise TweakError("graphics preference uses an unexpected registry value; no change made")
            gpu_value = self.backend.high_performance_gpu_value(gpu["value"] if gpu["exists"] else "") if game_path else ""
            change_mode = "game-mode" in selected and (not before_mode["exists"] or before_mode["value"] != 1)
            change_capture = "capture" in selected and any(not x["exists"] or x["value"] != 0 for x in capture)
            change_plan = "power" in selected and before_plan != HIGH_PERFORMANCE
            change_gpu = bool(game_path) and (not gpu["exists"] or gpu["value"] != gpu_value)
            change_mmcss = "mmcss" in selected and (not mmcss["exists"] or mmcss["value"] != 10)
            if not (change_mode or change_capture or change_plan or change_gpu or change_mmcss):
                return ["selected settings are already active"]
            applied_plan = HIGH_PERFORMANCE if self.backend.has_plan(HIGH_PERFORMANCE) else self.backend.new_guid()
            state = {
                "schema": 3,
                "owner_sid": self.store.owner_sid,
                "preset": preset,
                "game_mode": {"changed": change_mode, "exists": before_mode["exists"], "value": before_mode["value"], "kind": before_mode["kind"], "applied": 1},
                "power_plan": {"changed": change_plan, "original": before_plan, "applied": applied_plan, "created": change_plan and applied_plan != HIGH_PERFORMANCE},
                "capture": {"changed": change_capture, "original": capture, "applied": 0},
                "gpu": {"changed": change_gpu, "original": {"path": game_path, **gpu}, "applied": gpu_value},
                "mmcss": {"changed": change_mmcss, "original": mmcss, "applied": 10},
            }
            self.store.save_new(state)
            try:
                if change_mode:
                    self.backend.set_game_mode(1)
                if change_capture:
                    self.backend.set_capture(0)
                if change_plan:
                    if state["power_plan"]["created"]:
                        self.backend.create_high_performance_plan(applied_plan)
                    self.backend.set_active_plan(applied_plan)
                if change_gpu:
                    self.backend.set_gpu(game_path, gpu_value)
                if change_mmcss:
                    self.backend.set_mmcss(10)
            except Exception as apply_error:
                try:
                    self._restore_locked()
                except Exception as restore_error:
                    raise TweakError(f"apply failed: {apply_error}; restore failed: {restore_error}; saved state kept") from apply_error
                raise TweakError(f"apply failed: {apply_error}; original settings restored") from apply_error
            if not backup:
                try:
                    self.store.clear()
                except Exception as error:
                    return [f"{preset} controls applied", f"restore point could not be discarded: {error}; use restore later"]
                return [f"{preset} controls applied", "no backup retained; restore is unavailable"]
            return [f"{preset} controls applied", "use restore to return to saved settings"]

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
        if state["schema"] >= 2:
            gpu = state["gpu"]
            if gpu["changed"]:
                try:
                    previous = gpu["original"]
                    current = self.backend.get_gpu(previous["path"])
                    if current["exists"] and current["value"] == gpu["applied"] and current["kind"] == "string":
                        if previous["exists"]:
                            self.backend.set_gpu(previous["path"], previous["value"])
                        else:
                            self.backend.remove_gpu(previous["path"])
                        messages.append("graphics preference restored")
                    else:
                        messages.append("graphics preference changed elsewhere; current value kept")
                except Exception as error:
                    errors.append(f"graphics preference: {error}")
            capture = state["capture"]
            if capture["changed"]:
                try:
                    current = self.backend.get_capture()
                    for index, previous in enumerate(capture["original"]):
                        if current[index]["exists"] and current[index]["kind"] == "dword" and current[index]["value"] == 0:
                            if previous["exists"]:
                                self.backend.set_capture_one(index, previous["value"])
                            else:
                                self.backend.remove_capture_one(index)
                        else:
                            messages.append(f"capture setting {index + 1} changed elsewhere; current value kept")
                    messages.append("capture settings restored")
                except Exception as error:
                    errors.append(f"game capture: {error}")
        if state["schema"] == 3:
            mmcss = state["mmcss"]
            if mmcss["changed"]:
                try:
                    current = self.backend.get_mmcss()
                    if current["exists"] and current["kind"] == "dword" and current["value"] == 10:
                        if mmcss["original"]["exists"]:
                            self.backend.set_mmcss(mmcss["original"]["value"])
                        else:
                            self.backend.remove_mmcss()
                        messages.append("scheduler reserve restored; reboot to complete")
                    else:
                        messages.append("scheduler reserve changed elsewhere; current value kept")
                except Exception as error:
                    errors.append(f"scheduler reserve: {error}")
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
        if state["schema"] >= 2 and plan["created"]:
            try:
                if self.backend.get_active_plan() != plan["applied"] and self.backend.has_plan(plan["applied"]):
                    self.backend.delete_plan(plan["applied"])
                    messages.append("temporary power plan removed")
            except Exception as error:
                errors.append(f"temporary power plan: {error}")
        if errors:
            raise TweakError("restore incomplete: " + "; ".join(errors) + "; saved state kept")
        self.store.clear()
        messages.append("restore complete")
        return messages
