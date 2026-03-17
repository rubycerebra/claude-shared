[CmdletBinding()]
param(
    [string]$DistroName = "Ubuntu",
    [string]$LinuxUser = "jim",
    [switch]$RunDoctor
)

$wslExe = Join-Path $env:SystemRoot "System32\wsl.exe"
if (-not (Test-Path $wslExe)) {
    throw "wsl.exe not found at $wslExe"
}

$linuxCommand = "~/.claude/scripts/wsl2-start-runtime.sh"
if ($RunDoctor) {
    $linuxCommand += " --doctor"
}

$arguments = "-d `"$DistroName`" -u `"$LinuxUser`" -- bash -lc `"$linuxCommand`""
Write-Host "Running: $wslExe $arguments"
& $wslExe -d $DistroName -u $LinuxUser -- bash -lc $linuxCommand
