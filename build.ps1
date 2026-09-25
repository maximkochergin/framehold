param([string]$Python)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Python) {
    $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'python not found. pass -Python with the path to a python installation that has nuitka.'
}

$icon = Join-Path $root 'assets\framehold.ico'
$source = Join-Path $root 'framehold.py'
$output = Join-Path $root 'dist'
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw 'icon is missing.' }

$versionMatch = [regex]::Match((Get-Content -LiteralPath (Join-Path $root 'framehold_core.py') -Raw), '(?m)^VERSION = "(\d+\.\d+\.\d+)"\r?$')
if (-not $versionMatch.Success) { throw 'cannot read the project version.' }
$version = $versionMatch.Groups[1].Value
$testScript = 'import sys, unittest; sys.path.insert(0, sys.argv[1]); suite = unittest.defaultTestLoader.discover(sys.argv[2], pattern="test_*.py"); result = unittest.TextTestRunner().run(suite); raise SystemExit(not result.wasSuccessful())'

Push-Location -LiteralPath $root
try {
    & $Python -I -c $testScript $root (Join-Path $root 'tests')
    if ($LASTEXITCODE -ne 0) { throw 'tests failed.' }

    & $Python -I -m nuitka `
        --onefile `
        --zig `
        --windows-uac-admin `
        --windows-icon-from-ico=$icon `
        --output-dir=$output `
        --output-filename=framehold.exe `
        --product-name=framehold `
        --product-version=$version `
        --file-version="${version}.0" `
        --file-description='framehold - fortnite session utility' `
        $source
    if ($LASTEXITCODE -ne 0) { throw 'nuitka build failed.' }
}
finally {
    Pop-Location
}

$binary = Join-Path $output 'framehold.exe'
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'build finished without an exe.' }
Get-FileHash -LiteralPath $binary -Algorithm SHA256 | Select-Object Path,Hash
