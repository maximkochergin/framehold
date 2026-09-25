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

& $Python -m unittest discover -s (Join-Path $root 'tests') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'tests failed.' }

& $Python -m nuitka `
    --onefile `
    --zig `
    --assume-yes-for-downloads `
    --windows-uac-admin `
    --windows-icon-from-ico=$icon `
    --output-dir=$output `
    --output-filename=framehold.exe `
    --product-name=framehold `
    --product-version=0.2.0 `
    --file-version=0.2.0.0 `
    --file-description='framehold - fortnite session utility' `
    $source
if ($LASTEXITCODE -ne 0) { throw 'nuitka build failed.' }

$binary = Join-Path $output 'framehold.exe'
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'build finished without an exe.' }
Get-FileHash -LiteralPath $binary -Algorithm SHA256 | Select-Object Path,Hash
