"""framehold terminal interface."""

from __future__ import annotations

import argparse
import os
import subprocess
import textwrap

from framehold_core import Controller, TweakError, VERSION

CONTROLS = (
    ("game-mode", "game mode", "asks windows to prioritize the game over background activity; no fixed fps gain"),
    ("capture", "background capture", "stops windows game recording; may free cpu, gpu and disk bandwidth"),
    ("power", "power plan", "uses high performance power; may reduce power-saving stalls but increases heat"),
    ("gpu", "graphics preference", "requests the high performance gpu for fortnite on hybrid laptops"),
    ("mmcss", "cpu scheduler / test", "sets the mmcss low-priority cpu reserve to 10%; conditional effect; may hurt background audio; reboot"),
)


def say(text: str = "", indent: str = "  "):
    for line in textwrap.wrap(str(text).lower(), width=66, break_long_words=False, break_on_hyphens=False) or [""]:
        print(indent + line)


def header(section: str):
    print(f"\n  framehold / {section:<42} {VERSION}")
    print()


def ask(prompt: str = "choose") -> str:
    try:
        return input(f"  {prompt} > ").strip().lower()
    except EOFError:
        return "0"


def ask_path(prompt: str) -> str:
    try:
        return input(f"  {prompt} > ").strip().strip('"')
    except EOFError:
        return ""


def pause():
    try:
        input("  enter to continue  ")
    except EOFError:
        pass


def status(controller: Controller):
    state = controller.status()
    header("status")
    for label, value in (
        ("fortnite", "running" if state["game_running"] else "not running"),
        ("game mode", state["game_mode"]), ("capture", state["capture"]),
        ("cpu scheduler", state["scheduler"]), ("power plan", state["plan_name"]),
        ("gpu scheduling", state["hags"]),
        ("restore point", state["saved_state"]),
    ):
        say(f"{label:<17} {value}")
    say()


def scan(controller: Controller):
    from framehold_audit import analyze_inventory, collect_inventory, summarize_inventory
    header("system scan")
    say("reading windows inventory. no settings are changed.")
    data = collect_inventory()
    for line in summarize_inventory(data):
        say(line)
    say()
    for index, item in enumerate(analyze_inventory(data, controller.status()), 1):
        say(f"{index:02}  {item['title']}")
        say(item["detail"], "    ")
    say()
    say("driver versions are inventory, not a claim that a newer driver exists.")


def latency(controller: Controller, region: str = "eu"):
    from framehold_audit import collect_inventory, measure_ping
    header("input lag")
    data = collect_inventory()
    say("01  input device")
    say("polling rate belongs to device firmware and vendor software. framehold does not overclock usb devices.", "    ")
    say("02  render queue")
    say("fortnite supports nvidia reflex. when enabled, reflex overrides driver ultra low latency; framehold does not overwrite nvidia profile inspector.", "    ")
    say("03  display")
    say("refresh and sync affect frame delivery. your game resolution and render scale stay unchanged.", "    ")
    say("04  network")
    networks = data.get("net") or []
    if isinstance(networks, dict):
        networks = [networks]
    if any("wi-fi" in str(item.get("Name", "")).lower() for item in networks if isinstance(item, dict)):
        say("wi-fi is active; radio interference can increase jitter.", "    ")
    try:
        result = measure_ping(region)
        if result["received"]:
            say(f"{region} icmp  {result['received']}/{result['sent']} replies; median {result['median_ms']:.1f} ms; spread {result['spread_ms']:.1f} ms", "    ")
        else:
            say("icmp did not reply; this does not prove fortnite is unreachable.", "    ")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        say("network probe unavailable; no network changes made.", "    ")
    say("icmp is a route baseline, not in-game input lag. tcp tuning is not a proven fortnite input-lag control.", "    ")


def controls():
    header("choose controls")
    for index, (_, title, detail) in enumerate(CONTROLS, 1):
        say(f"{index}  {title}")
        say(detail, "    ")
        say()
    say("game files and in-game settings are never changed.")


def choose_controls(raw: str) -> set[str]:
    entries = {token.strip() for token in raw.replace(" ", ",").split(",") if token.strip()}
    valid = {str(index): key for index, (key, _, _) in enumerate(CONTROLS, 1)}
    if not entries or entries - set(valid):
        raise TweakError("choose one or more control numbers")
    return {valid[token] for token in entries}


def review_apply(controller: Controller, features: set[str], path: str | None, backup: bool):
    header("review changes")
    for line in controller.preview("competitive", features, path):
        say(line)
    say()
    if backup:
        say("a restore point is stored before changes. only one saved session can be active.")
    else:
        say("warning: no restore point will be retained. one-click restore will be unavailable for these changes.")
    if ask("type apply") != "apply":
        say("cancelled")
        return
    if not backup and ask("type no-backup to confirm") != "no-backup":
        say("cancelled")
        return
    for line in controller.apply("competitive", features, path, backup=backup):
        say(line)


def faq():
    header("faq")
    answers = (
        ("who owns framehold?", "owned and maintained by maximkochergin. independent of epic games, microsoft and nvidia."),
        ("will this guarantee more fps?", "no. a control matters only when its bottleneck is present. compare measured frame times in the same scene."),
        ("will it change my fortnite graphics?", "no. files, resolution, render scale and visuals are left as they are."),
        ("will anti-cheat ban me?", "framehold does not inject, alter protected files or memory, or bypass anti-cheat. no third party can guarantee an anti-cheat decision."),
        ("does it conflict with nvidia profile inspector?", "framehold never writes nvidia driver profiles. its gpu control uses only the windows per-app preference."),
        ("what does no backup mean?", "the change is rolled back if applying fails, but the restore point is removed after success. later reversal is manual."),
        ("why no timer or tcp speed hack?", "microsoft documents unused or clamped registry values. blind timer and network changes can cause instability without proven game benefit."),
        ("how do i prove a change helped?", "export a fortnite csv from presentmon, then use benchmark before and after one control in the same scene."),
    )
    for question, answer in answers:
        say(question)
        say(answer, "    ")
        say()


def benchmark(path: str):
    from framehold_benchmark import analyze_csv
    result = analyze_csv(path)
    header("benchmark / presentmon csv")
    say(f"frames             {result['frames']}")
    say(f"average fps        {result['average_fps']:.1f}")
    say(f"median frame       {result['median_ms']:.2f} ms")
    say(f"p95 frame          {result['p95_ms']:.2f} ms")
    say(f"p99 frame          {result['p99_ms']:.2f} ms")
    if result["cpu_busy_ms"] is not None:
        say(f"average cpu busy   {result['cpu_busy_ms']:.2f} ms")
    if result["gpu_busy_ms"] is not None:
        say(f"average gpu busy   {result['gpu_busy_ms']:.2f} ms")
    if result["pc_latency_ms"] is not None:
        say(f"median pc latency  {result['pc_latency_ms']:.2f} ms")
    say("these are presentation metrics, not a guaranteed click-to-photon latency measurement.")


def menu(controller: Controller):
    while True:
        header("home")
        for line in (
            "1  scan my pc       find bottlenecks in this setup",
            "2  tune             select and explain controls",
            "3  input lag        device, rendering, display, network",
            "4  restore          return to the saved state",
            "5  faq              ownership and safety",
            "6  status           current windows settings",
            "7  focus game       temporary process priority",
            "8  benchmark        analyze a presentmon csv",
            "0  exit",
        ):
            say(line)
        selected = ask()
        if selected == "0":
            return
        try:
            if selected == "1":
                scan(controller)
            elif selected == "2":
                controls()
                raw = ask("numbers, for example 1,2,4")
                if raw == "0":
                    continue
                features = choose_controls(raw)
                path = (ask_path("fortnite exe path, or enter to detect") or None) if "gpu" in features else None
                backup = ask("keep a restore point? [y/n]") != "n"
                review_apply(controller, features, path, backup)
            elif selected == "3":
                latency(controller)
            elif selected == "4":
                header("restore")
                if ask("type restore") == "restore":
                    for line in controller.restore():
                        say(line)
            elif selected == "5":
                faq()
            elif selected == "6":
                status(controller)
            elif selected == "7":
                header("focus game")
                say("above-normal cpu priority until fortnite exits. windows may deny access.")
                if ask("type focus") == "focus":
                    for line in controller.backend.focus_game():
                        say(line)
            elif selected == "8":
                path = ask_path("presentmon csv path")
                if path:
                    benchmark(path)
            else:
                say("unknown choice")
        except (TweakError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            say("error: " + str(error))
        pause()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="framehold", description="windows session controls for fortnite")
    parser.add_argument("--action", choices=("menu", "scan", "latency", "benchmark", "status", "preview", "apply", "restore", "focus", "faq"), default="menu")
    parser.add_argument("--preset", choices=("balanced", "competitive"), default="balanced")
    parser.add_argument("--features", metavar="controls", help="comma-separated: game-mode,capture,power,gpu,mmcss")
    parser.add_argument("--game-exe", metavar="path", help="full fortnite executable path for gpu preference")
    parser.add_argument("--csv", metavar="path", help="presentmon csv path for benchmark analysis")
    parser.add_argument("--region", choices=("eu", "nae", "nac", "naw"), default="eu")
    parser.add_argument("--no-backup", action="store_true", help="discard restore point after a successful change")
    parser.add_argument("--accept-no-backup", action="store_true", help="acknowledge no-backup warning for this run")
    parser.add_argument("--version", action="version", version="framehold " + VERSION)
    args = parser.parse_args(argv)
    if os.name != "nt":
        say("framehold requires windows")
        return 1
    from framehold_windows import RegistryStore, WindowsBackend
    try:
        backend = WindowsBackend()
        controller = Controller(backend, RegistryStore(backend.owner_sid))
        features = {part.strip() for part in args.features.lower().split(",")} if args.features else None
        if args.action == "menu":
            menu(controller)
        elif args.action == "scan":
            scan(controller)
        elif args.action == "latency":
            latency(controller, args.region)
        elif args.action == "benchmark":
            if not args.csv:
                raise TweakError("pass --csv with a presentmon export")
            benchmark(args.csv)
        elif args.action == "status":
            status(controller)
        elif args.action == "faq":
            faq()
        elif args.action == "preview":
            for line in controller.preview(args.preset, features, args.game_exe):
                say(line)
        elif args.action == "apply":
            if args.no_backup:
                say("warning: no restore point will be retained after success.")
                if not args.accept_no_backup:
                    raise TweakError("pass --accept-no-backup to confirm this run")
            for line in controller.preview(args.preset, features, args.game_exe):
                say(line)
            for line in controller.apply(args.preset, features, args.game_exe, backup=not args.no_backup):
                say(line)
        elif args.action == "restore":
            for line in controller.restore():
                say(line)
        else:
            for line in backend.focus_game():
                say(line)
        return 0
    except (TweakError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        say("error: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
