"""framehold: a focused Windows terminal companion for Fortnite."""

from __future__ import annotations

import argparse
import os
import shutil

from framehold_core import Controller, HIGH_PERFORMANCE, TweakError, VERSION

def line(text: str = ""):
    print(text)


def header():
    line()
    line("       /\\                /\\")
    line("  ____/  \\____    _____/  \\____")
    line(" /            " + chr(92) + "__/             " + chr(92))
    line("    framehold")
    line("    quiet tools for a steadier session")
    line()


def item(label: str, value: str):
    line(f"    {label:<18} {value}")


def show_status(controller: Controller):
    header()
    line("    system")
    state = controller.status()
    item("power plan", state["plan"])
    item("game mode", state["game_mode"])
    item("capture", state["capture"])
    item("fortnite", "running" if state["game_running"] else "not running")
    item("saved state", state["saved_state"])
    line()
    line("    results depend on hardware, thermals and the game settings.")
    line()


def show_preview(controller: Controller, preset: str, features: set[str] | None = None, game_exe: str | None = None):
    header()
    line(f"    {preset} / preview")
    line()
    for value in controller.preview(preset, features, game_exe):
        line("    " + value)
    line("    restore         previous values are saved before changes")
    line()


def show_messages(messages: list[str]):
    line()
    for message in messages:
        line("    " + message)
    line()


def select() -> str:
    try:
        return input("    select  ").strip().lower()
    except EOFError:
        return "00"


def confirmed() -> bool:
    try:
        return input("    apply? [y/n]  ").strip().lower() == "y"
    except EOFError:
        return False


def show_menu(controller: Controller):
    header()
    if shutil.get_terminal_size((100, 30)).columns < 88:
        line("    01   overview")
        line("    02   balanced")
        line("    03   competitive")
        line("    04   restore")
        line("    05   focus game")
        line("    06   custom controls")
        line("    00   exit")
        line()
        return
    state = controller.status()
    plan = {"381b4222-f694-41f0-9685-ff5bb260df2e": "balanced", HIGH_PERFORMANCE: "high performance"}.get(state["plan"], "custom")
    rows = [
        ("session / overview", "menu / actions"),
        ("", ""),
        (f"power plan   {plan}", "01   overview"),
        (f"game mode    {state['game_mode']}", "02   balanced"),
        (f"capture      {state['capture']}", "03   competitive"),
        (f"fortnite     {'running' if state['game_running'] else 'not running'}", "04   restore"),
        (f"saved state  {state['saved_state']}", "05   focus game"),
        ("", "06   custom controls"),
        ("", "00   exit"),
    ]
    for left, right in rows:
        line(f"    {left:<39} {right}")
    line()


def menu(controller: Controller):
    while True:
        show_menu(controller)
        choice = select().lstrip("0") or "0"
        try:
            if choice == "0":
                return
            if choice == "1":
                show_status(controller)
            elif choice in ("2", "3"):
                preset = "balanced" if choice == "2" else "competitive"
                show_preview(controller, preset)
                if confirmed():
                    show_messages(controller.apply(preset))
            elif choice == "4":
                show_messages(controller.restore())
            elif choice == "5":
                show_messages(controller.backend.focus_game())
            elif choice == "6":
                line("    controls: game-mode, capture, power, gpu")
                try:
                    raw = input("    select (comma separated)  ").strip().lower()
                    features = {part.strip() for part in raw.split(",")}
                    path = input("    fortnite exe path (enter to detect)  ").strip() if "gpu" in features else None
                except EOFError:
                    return
                show_preview(controller, "competitive", features, path or None)
                if confirmed():
                    show_messages(controller.apply("competitive", features, path or None))
            else:
                line("    unknown choice")
        except (TweakError, OSError, ValueError) as error:
            line("    " + str(error).lower())
        line()
        try:
            input("    enter to continue  ")
        except EOFError:
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="framehold", description="quiet tools for a steadier fortnite session")
    parser.add_argument("--action", choices=("menu", "status", "preview", "apply", "restore", "focus"), default="menu")
    parser.add_argument("--preset", choices=("balanced", "competitive"), default="balanced")
    parser.add_argument("--features", metavar="controls", help="comma-separated controls: game-mode,capture,power,gpu")
    parser.add_argument("--game-exe", metavar="path", help="full fortnite executable path for the gpu control")
    parser.add_argument("--version", action="version", version="framehold " + VERSION)
    args = parser.parse_args(argv)
    features = {part.strip() for part in args.features.lower().split(",")} if args.features else None
    if os.name != "nt":
        line("    framehold requires windows")
        return 1
    from framehold_windows import RegistryStore, WindowsBackend

    try:
        backend = WindowsBackend()
        controller = Controller(backend, RegistryStore(backend.owner_sid))
        if args.action == "menu":
            menu(controller)
        elif args.action == "status":
            show_status(controller)
        elif args.action == "preview":
            show_preview(controller, args.preset, features, args.game_exe)
        elif args.action == "apply":
            show_preview(controller, args.preset, features, args.game_exe)
            show_messages(controller.apply(args.preset, features, args.game_exe))
        elif args.action == "restore":
            show_messages(controller.restore())
        elif args.action == "focus":
            show_messages(backend.focus_game())
        return 0
    except (TweakError, OSError, ValueError) as error:
        line("    error: " + str(error).lower())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
