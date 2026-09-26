"""Read-only Windows inventory and evidence-based findings."""

from __future__ import annotations

import json
import os
import subprocess
import ctypes as ct
import datetime as dt
import re
from statistics import median


SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$result = @{}
try {
  $result.os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,BuildNumber,TotalVisibleMemorySize,FreePhysicalMemory
} catch { $result.os_error = $_.Exception.Message }
try {
  $result.cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfLogicalProcessors
} catch { $result.cpu_error = $_.Exception.Message }
try {
  $result.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate,CurrentRefreshRate)
} catch { $result.gpu_error = $_.Exception.Message }
try {
  $result.input = @(Get-PnpDevice -Class Mouse,Keyboard -ErrorAction Stop | Select-Object Class,FriendlyName,Status)
} catch { $result.input_error = $_.Exception.Message }
try {
  $result.battery = @(Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining,BatteryStatus)
} catch { $result.battery_error = $_.Exception.Message }
try {
  $result.disk = @(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus)
} catch { $result.disk_error = $_.Exception.Message }
try {
  $result.net = @(Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription,LinkSpeed,MediaConnectionState,DriverVersion,DriverDate)
} catch { $result.net_error = $_.Exception.Message }
try {
  $result.net_stats = @(Get-NetAdapterStatistics | Select-Object Name,ReceivedDiscardedPackets,ReceivedPacketErrors,OutboundDiscardedPackets,OutboundPacketErrors)
} catch { $result.net_stats_error = $_.Exception.Message }
try {
  $result.services = @(Get-Service -Name MMCSS,DoSvc,SysMain,WSearch -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType)
} catch { $result.services_error = $_.Exception.Message }
try {
  $result.processes = @(Get-Process | Sort-Object CPU -Descending | Select-Object -First 12 ProcessName,CPU,WorkingSet64)
} catch { $result.processes_error = $_.Exception.Message }
try {
  $result.memory_processes = @(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 ProcessName,WorkingSet64)
} catch { $result.memory_processes_error = $_.Exception.Message }
try {
  $result.tools = @(Get-Process -Name @('nvidiaProfileInspector','obs64','Discord','NVIDIA Share','GameBar','Overwolf','Medal') -ErrorAction SilentlyContinue | Select-Object ProcessName,WorkingSet64)
} catch { $result.tools_error = $_.Exception.Message }
try {
  $result.tcp = @(Get-NetTCPSetting -ErrorAction Stop | Where-Object SettingName -eq 'Internet' | Select-Object SettingName,AutoTuningLevelLocal)
} catch { $result.tcp_error = $_.Exception.Message }
$result | ConvertTo-Json -Depth 5 -Compress
"""


def _system_directory() -> str:
    buffer = ct.create_unicode_buffer(32768)
    get_directory = ct.WinDLL("kernel32", use_last_error=True).GetSystemDirectoryW
    get_directory.argtypes = [ct.c_wchar_p, ct.c_uint]
    get_directory.restype = ct.c_uint
    length = get_directory(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise RuntimeError("cannot locate the windows system directory")
    return buffer.value


def _run_trusted_powershell(command: str, timeout: int) -> subprocess.CompletedProcess:
    system_dir = _system_directory()
    ps_dir = os.path.join(system_dir, "WindowsPowerShell", "v1.0")
    trusted_env = os.environ.copy()
    trusted_env["PSModulePath"] = os.path.join(ps_dir, "Modules")
    trusted_env["PATH"] = system_dir + os.pathsep + ps_dir
    return subprocess.run(
        [os.path.join(ps_dir, "powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=system_dir, env=trusted_env,
    )


def collect_inventory(timeout: int = 35) -> dict:
    if os.name != "nt":
        raise RuntimeError("windows is required")
    result = _run_trusted_powershell(SCRIPT, timeout)
    if result.returncode:
        raise RuntimeError("windows inventory command failed")
    try:
        data = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("windows inventory returned invalid data") from error
    if not isinstance(data, dict):
        raise RuntimeError("windows inventory returned invalid data")
    return data


def _array(value) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _driver_age_days(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        if value.startswith("/Date("):
            match = re.match(r"/Date\((\d+)", value)
            if not match:
                return None
            date = dt.datetime.fromtimestamp(int(match.group(1)) / 1000, tz=dt.timezone.utc).date()
        else:
            date = dt.date.fromisoformat(value[:10])
        return (dt.date.today() - date).days
    except (ValueError, OverflowError, OSError):
        return None


def analyze_inventory(data: dict, settings: dict) -> list[dict]:
    findings = []
    def add(area: str, title: str, detail: str, severity: str = "note"):
        findings.append({"area": area, "title": title, "detail": detail, "severity": severity})

    os_data = data.get("os") if isinstance(data.get("os"), dict) else {}
    total_kb = os_data.get("TotalVisibleMemorySize")
    free_kb = os_data.get("FreePhysicalMemory")
    if isinstance(total_kb, (int, float)) and isinstance(free_kb, (int, float)) and total_kb > 0:
        total_gb = total_kb / 1048576
        free_gb = free_kb / 1048576
        if total_gb < 8:
            add("hardware", "limited memory", f"{total_gb:.1f} gb installed; memory pressure can cause stutter", "attention")
        elif free_gb < 2:
            add("hardware", "low free memory", f"{free_gb:.1f} gb currently available; inspect background apps", "attention")
    disks = _array(data.get("disk"))
    if any(str(item.get("MediaType", "")).lower() == "hdd" for item in disks):
        add("storage", "hard drive detected", "if fortnite is on this drive, asset streaming may hitch; confirm install location", "attention")
    if any(str(item.get("HealthStatus", "")).lower() not in ("healthy", "") for item in disks):
        add("storage", "disk health needs attention", "check the affected drive before changing performance settings", "attention")
    for device in _array(data.get("input")):
        if str(device.get("Status", "")).lower() not in ("ok", ""):
            add("input", "input device has a reported issue", str(device.get("FriendlyName", "device")) + "; inspect its driver and connection", "attention")
    for service in _array(data.get("services")):
        if str(service.get("Name", "")).lower() == "mmcss" and str(service.get("Status", "")).lower() not in ("running", "4"):
            add("windows", "multimedia scheduler is stopped", "mmcss-dependent priority controls cannot help while this service is stopped", "attention")
    if settings.get("game_mode") == "off":
        add("windows", "game mode is off", "game mode can limit background interference; available as a reversible control")
    if settings.get("capture") != "off":
        add("windows", "background capture may be active", "background recording can consume cpu, gpu and storage resources")
    hags = settings.get("hags")
    if hags == "off":
        add("graphics", "gpu scheduling is off", "epic recommends testing this when supported; a restart is required")
    if settings.get("plan") == "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c" and _array(data.get("battery")):
        add("power", "high performance on a laptop", "check battery use and heat when away from ac power")
    active = _array(data.get("net"))
    if any("wi-fi" in str(item.get("Name", "")).lower() or "wireless" in str(item.get("InterfaceDescription", "")).lower() for item in active):
        add("network", "wireless network in use", "packet loss and jitter are more likely than on wired ethernet; measure before changing settings")
    for item in active:
        if "wi-fi" in str(item.get("Name", "")).lower() or "wireless" in str(item.get("InterfaceDescription", "")).lower():
            age = _driver_age_days(item.get("DriverDate"))
            if age is not None and age > 730:
                add("network", "wireless driver is older", f"installed driver {item.get('DriverVersion', '?')} is {age // 365} years old; check the laptop maker's supported releases if jitter persists")
    for item in _array(data.get("gpu")):
        if "intel" in str(item.get("Name", "")).lower():
            age = _driver_age_days(item.get("DriverDate"))
            if age is not None and age > 1095:
                add("graphics", "integrated gpu driver is older", f"installed driver {item.get('DriverVersion', '?')} is {age // 365} years old; review oem compatibility before changing it")
    processes = _array(data.get("tools"))
    overlays = ("obs64", "discord", "nvidiashare", "gamebar", "overwolf", "medal", "nvidiaprofileinspector")
    present = sorted({str(item.get("ProcessName", "")).lower() for item in processes if str(item.get("ProcessName", "")).lower() in overlays})
    if present:
        add("processes", "capture or profile tools running", ", ".join(present) + "; inspect their load and profiles before tuning")
    memory_heavy = [item for item in _array(data.get("memory_processes")) if isinstance(item.get("WorkingSet64"), (int, float)) and item["WorkingSet64"] >= 1073741824 and str(item.get("ProcessName", "")).lower() not in ("fortniteclient-win64-shipping", "memory compression")]
    if memory_heavy:
        names = ", ".join(sorted({str(item.get("ProcessName", "")).lower() for item in memory_heavy})[:3])
        add("processes", "memory-heavy processes found", names + "; close only if unneeded and after saving work")
    stats = _array(data.get("net_stats"))
    active_names = {str(item.get("Name", "")).lower() for item in active}
    for item in stats:
        if str(item.get("Name", "")).lower() not in active_names:
            continue
        try:
            errors = sum(int(item.get(key) or 0) for key in ("ReceivedPacketErrors", "OutboundPacketErrors"))
        except (TypeError, ValueError):
            continue
        if errors > 0:
            add("network", "adapter packet errors recorded", f"{item.get('Name', 'adapter')}: {errors} cumulative errors; compare again after a play session", "attention")
    tcp = _array(data.get("tcp"))
    if tcp and str(tcp[0].get("AutoTuningLevelLocal", "")).lower() not in ("normal", "3"):
        add("network", "tcp receive tuning differs from normal", "this can affect downloads; it is not a proven fortnite input-lag control")
    for name in ("os", "cpu", "gpu", "input", "battery", "disk", "net", "net_stats", "services", "processes", "memory_processes", "tools", "tcp"):
        if name + "_error" in data:
            add("audit", name + " unavailable", "windows did not return this inventory section")
    if not findings:
        add("system", "no clear bottleneck found", "compare measured frame times and network jitter before changing advanced settings")
    return findings


def summarize_inventory(data: dict) -> list[str]:
    lines = []
    os_data = data.get("os") if isinstance(data.get("os"), dict) else {}
    if os_data:
        lines.append("windows   " + str(os_data.get("Caption", "unknown")).lower() + " / build " + str(os_data.get("BuildNumber", "?")))
    cpu = data.get("cpu") if isinstance(data.get("cpu"), dict) else {}
    if cpu:
        lines.append("cpu       " + str(cpu.get("Name", "unknown")).strip().lower())
    for gpu in _array(data.get("gpu")):
        lines.append("gpu       " + str(gpu.get("Name", "unknown")).lower() + " / driver " + str(gpu.get("DriverVersion", "?")))
    for device in _array(data.get("input"))[:4]:
        lines.append(("input     " + str(device.get("FriendlyName", "unknown")) + " / " + str(device.get("Status", "?"))).lower())
    for adapter in _array(data.get("net")):
        version = adapter.get("DriverVersion")
        suffix = " / driver " + str(version) if version else ""
        lines.append("network   " + str(adapter.get("Name", "unknown")).lower() + " / " + str(adapter.get("LinkSpeed", "?")) + suffix)
    return lines


PING_HOSTS = {
    "eu": "ping-eu.ds.on.epicgames.com",
    "nae": "ping-nae.ds.on.epicgames.com",
    "nac": "ping-nac.ds.on.epicgames.com",
    "naw": "ping-naw.ds.on.epicgames.com",
}


def measure_ping(region: str = "eu") -> dict:
    if region not in PING_HOSTS or os.name != "nt":
        raise RuntimeError("unsupported network probe")
    command = (
        "$samples = @(Test-Connection -ComputerName '" + PING_HOSTS[region] +
        "' -Count 8 -ErrorAction SilentlyContinue | ForEach-Object { $_.ResponseTime }); "
        "$samples | ConvertTo-Json -Compress"
    )
    result = _run_trusted_powershell(command, 20)
    if result.returncode:
        raise RuntimeError("network probe failed")
    try:
        decoded = json.loads(result.stdout) if result.stdout.strip() else []
    except ValueError as error:
        raise RuntimeError("network probe returned invalid data") from error
    values = decoded if isinstance(decoded, list) else [decoded]
    values = [float(value) for value in values if isinstance(value, (int, float)) and value >= 0]
    return {
        "sent": 8, "received": len(values),
        "median_ms": median(values) if values else 0.0,
        "spread_ms": max(values) - min(values) if values else 0.0,
    }
