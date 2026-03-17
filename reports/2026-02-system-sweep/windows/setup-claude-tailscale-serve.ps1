[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Target = "127.0.0.1:8765"
)

$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $tailscale) {
    throw "tailscale command not found in PATH"
}

try {
    $statusJson = & $tailscale.Source serve status --json | ConvertFrom-Json -ErrorAction Stop
} catch {
    $statusJson = $null
}

$alreadyConfigured = $false
if ($statusJson -and $statusJson.Web) {
    $webJson = $statusJson.Web | ConvertTo-Json -Depth 10
    if ($webJson -match [regex]::Escape($Target)) {
        $alreadyConfigured = $true
    }
}

if ($alreadyConfigured) {
    Write-Host "Tailscale serve already points at $Target"
    & $tailscale.Source serve status
    exit 0
}

if ($PSCmdlet.ShouldProcess("tailscale serve", "Expose $Target on the tailnet")) {
    & $tailscale.Source serve --bg $Target
    Write-Host "Configured Tailscale serve for $Target"
    & $tailscale.Source serve status
}
