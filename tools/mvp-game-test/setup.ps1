param(
    [Parameter(Mandatory=$false)]
    [string]$InstallDir = "C:\AI\mvp-game-test",
    [switch]$EnableVirtualGamepad
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceResolved = (Resolve-Path $ScriptDir).Path
$InstallFull = [System.IO.Path]::GetFullPath($InstallDir)

Write-Host "Installing MVP game-test MCP agent into: $InstallFull"
if (-not (Test-Path $InstallFull)) { New-Item -ItemType Directory -Path $InstallFull | Out-Null }

$Files = @("mvp_game_test.py","requirements.txt","requirements-gamepad.txt","codex-config-template.toml","set_test_target.py","run_local_smoke.py","setup.ps1","README.md","test_worker.py")
foreach ($File in $Files) {
    $Src = Join-Path $SourceResolved $File
    $Dst = Join-Path $InstallFull $File
    if (([System.IO.Path]::GetFullPath($Src)) -ne ([System.IO.Path]::GetFullPath($Dst))) { Copy-Item $Src $Dst -Force }
}

$SrcTests = Join-Path $SourceResolved "tests"
$DstTests = Join-Path $InstallFull "tests"
if (([System.IO.Path]::GetFullPath($SrcTests)) -ne ([System.IO.Path]::GetFullPath($DstTests))) {
    if (-not (Test-Path $DstTests)) { New-Item -ItemType Directory -Path $DstTests | Out-Null }
    Copy-Item "$SrcTests\*" $DstTests -Force
}


if (-not (Test-Path "$InstallFull\.venv\Scripts\python.exe")) {
    & py -3.11 -m venv "$InstallFull\.venv"
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python 3.11 environment." }
}
& "$InstallFull\.venv\Scripts\python.exe" -m pip install -r "$InstallFull\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Could not install game-test dependencies." }

if ($EnableVirtualGamepad) {
    & "$InstallFull\.venv\Scripts\python.exe" -m pip install -r "$InstallFull\requirements-gamepad.txt"
    if ($LASTEXITCODE -ne 0) { throw "Could not install virtual gamepad support." }
    Write-Host "Virtual gamepad Python support installed. A compatible ViGEm driver must also exist on Windows."
}

Write-Host "Installation complete. Configure Codex using codex-config-template.toml, then restart the Codex Windows app."
