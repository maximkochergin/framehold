# framehold

windows session diagnostics and reversible controls for fortnite.

![framehold in cmd](assets/cmd.png)

## what it does

start with **scan my pc**. framehold reads the installed gpu and driver versions, input devices, memory, storage health, active network adapters and error counters, selected services, and resource-heavy or overlay processes. findings are tied to the machine being scanned. the **input lag** page separates device polling, the render queue, display timing, and network delay; it can measure icmp latency to an epic test host. an icmp result is not an in-game latency measurement. the scan cannot infer temperature from hardware without a supported sensor interface or prove that an installed driver is the latest release.

**benchmark** reads a fortnite csv exported by [presentmon](https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md) and reports average fps, median/p95/p99 frame time, and cpu/gpu busy time when present. run the same scene before and after one control. framehold reads the csv; it does not run or modify presentmon.

the **tune** page lets you combine individual controls. each one shows its mechanism before applying:

| control | mechanism and limit |
| --- | --- |
| game mode | asks windows to reduce background interference during games; no fixed fps gain |
| background capture | disables two per-user game recording settings, avoiding recording work when it would otherwise run |
| power plan | selects high performance or creates a temporary copy; may reduce power-saving stalls while increasing heat and battery use |
| graphics preference | requests the high performance gpu for fortnite in windows; useful on hybrid laptops, subject to driver routing |
| cpu scheduler / test | sets the mmcss low-priority cpu reserve to 10%; can matter only for threads that register with mmcss and may affect background audio; reboot to test |
| focus game | sets the verified running fortnite process to above-normal cpu priority until it exits |

framehold does not change fortnite files, visual settings, resolution, or render scale. it does not inject into the game or modify anti-cheat components. it never writes nvidia driver profiles, so nvidia profile inspector and other driver tools keep control of those settings.

## backups and restore

the default is a saved restore point before any persistent change. choose **restore** to put original values back; changes made by another tool after framehold applied its values are left alone. only one saved session can be active at once.

you can decline a retained backup for each application. framehold warns and requires an additional confirmation every time. it still keeps a temporary transaction record while applying, so a failed change can roll back. after a successful no-backup application, one-click restore is unavailable.

## use

download `framehold.exe` and `sha256sums.txt` from the [latest release](https://github.com/maximkochergin/framehold/releases/latest). compare the exe's sha-256 with the checksum file before running. the executable requests administrator rights and checks that elevation belongs to the signed-in account. nuitka packaging does not sign the binary or guarantee an antivirus result.

open the exe for the menu. direct actions are also available:

```text
framehold.exe --action scan
framehold.exe --action latency --region eu
framehold.exe --action benchmark --csv "c:\captures\fortnite.csv"
framehold.exe --action preview --features capture,gpu --game-exe "c:\path\to\fortnitegame\binaries\win64\fortniteclient-win64-shipping.exe"
framehold.exe --action apply --features capture,power
framehold.exe --action restore
```

for an application without a retained restore point, add `--no-backup --accept-no-backup`. this warning and acknowledgment are required on each run. `mmcss` is an experimental opt-in control and is never included in a preset.

## why some popular tweaks are absent

the mmcss `gpu priority` registry value is [documented by microsoft as unused](https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service). values below 10 for `systemresponsiveness` are clamped, so a common `0` recipe does not mean zero cpu reserve. global timer hacks, broad service disabling, and blanket tcp registry changes have no established fortnite fps or input-lag benefit and can destabilize a pc. nvidia notes that [reflex overrides driver ultra low latency](https://www.nvidia.com/en-us/geforce/guides/gfecnt/202010/system-latency-optimization-guide/) when both are enabled; framehold leaves those settings to the game and driver tools.

the current controls were reviewed against [epic's pc guidance](https://www.epicgames.com/help/c-34254770/c-38015632/a25544495), [microsoft's mmcss documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service), and the [nvidia latency guide](https://www.nvidia.com/en-us/geforce/guides/gfecnt/202010/system-latency-optimization-guide/) in september 2026. driver and game behavior can change; measure frame times and latency before trusting any gain.

## build

on windows, install python 3.14 and nuitka, then run `pwsh -file .\build.ps1 -python <path-to-python.exe>`. the script runs the tests, builds `dist\framehold.exe`, and prints its sha-256.

## faq

**who owns framehold?** owned and maintained by maximkochergin. the project is independent of epic games, microsoft, and nvidia.

**will it guarantee more fps?** no. gains depend on the actual bottleneck, hardware, drivers, thermals, and the game. compare the same scene before and after a single control.

**will it change my game graphics?** no. framehold does not read or write fortnite configuration files.

**is it compatible with nvidia profile inspector?** framehold does not import, reset, or write `.nip` files or nvidia driver profiles. use that application's own export feature before changing driver profiles there.
