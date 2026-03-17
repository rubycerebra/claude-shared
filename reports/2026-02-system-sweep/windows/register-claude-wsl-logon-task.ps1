[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DistroName = "Ubuntu",
    [string]$LinuxUser = "jim",
    [string]$TaskName = "Claude WSL Runtime (Logon)",
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

$wslArguments = "-d `"$DistroName`" -u `"$LinuxUser`" -- bash -lc `"$linuxCommand`""
$action = New-ScheduledTaskAction -Execute $wslExe -Argument $wslArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$userId = if ($env:USERDOMAIN) { "$($env:USERDOMAIN)\$($env:USERNAME)" } else { $env:USERNAME }
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
$description = "Starts the Claude WSL runtime after Windows logon via wsl2-start-runtime.sh. Best fit for the existing VNC-admin workflow."

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description

if ($PSCmdlet.ShouldProcess($TaskName, "Register scheduled task")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Write-Host "Registered scheduled task: $TaskName"
    Write-Host "Action: $wslExe $wslArguments"
    Write-Host "This logon-trigger path fits the current VNC workflow: sign into Windows via VNC and the WSL runtime will start."
}
