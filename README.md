# framehold

quiet session controls for fortnite on windows.

![framehold running in cmd](assets/cmd.png)

framehold shows the current power plan, game mode, game process, and saved state in a small terminal interface. it applies a profile only after showing the planned changes and keeps the original settings for restore.

## actions

| action | effect |
| --- | --- |
| `balanced` | turns on game mode and keeps the current power plan |
| `competitive` | turns on game mode and selects high performance when available |
| `focus game` | sets the current account's running fortnite process to above normal priority until it exits |
| `restore` | restores saved values while leaving external changes alone |

the in-game guide suggests settings to compare inside fortnite. framehold does not edit game files, install drivers, or change windows boot settings. performance depends on the pc, thermals, and game settings.

## get started

download `framehold.exe` and its checksum from the [latest release](https://github.com/maximkochergin/framehold/releases/latest). verify the sha-256 before running the executable. it requests administrator rights; the app stops changes when elevation belongs to a different signed-in account. nuitka packaging does not digitally sign the file or guarantee a particular antivirus result.

open the executable for the menu, or use a direct action:

```text
framehold.exe --action status
framehold.exe --action restore
```

`competitive` may increase power use and heat. use `restore` to return to the saved values. snapshots are stored under `hklm\software\framehold\state` for the executing account. an incomplete restore keeps its snapshot for another attempt.

if an older version left `%localappdata%\fortnite-tweaker\snapshot.json`, restore it with the version that created it before using this release. framehold does not import that writable file.

## build from source

on windows, install python 3.14 and nuitka, then run `pwsh -file .\build.ps1 -python <path-to-python.exe>`. the script runs tests before building `dist\framehold.exe` and prints its sha-256. running `python framehold.py` from source is also supported.

framehold is an independent project and is not affiliated with epic games.
