#!/usr/bin/env bash
# tailscale-route-check.sh — detect and auto-fix missing Tailscale OS routes on Mac.
# When Tailscale's daemon is running but didn't install the 100.64/10 route into the
# OS routing table, SSH and HTTP to Tailscale peers time out silently (ping works because
# it goes through the userspace daemon, not the OS stack). Fix: tailscale down && up.

set -euo pipefail

# Only run on macOS
[[ "$(uname)" == "Darwin" ]] || exit 0

TAILSCALE_PEER="100.73.88.14"  # NUC

# Check what interface the OS would use to reach the Tailscale peer
IFACE=$(route get "$TAILSCALE_PEER" 2>/dev/null | awk '/interface:/{print $2}')

# If already routing via utun (Tailscale), nothing to do
if [[ "$IFACE" == utun* ]]; then
    exit 0
fi

# Routes are missing — fix by cycling Tailscale
tailscale down 2>/dev/null || true
sleep 1
tailscale up 2>/dev/null || true
sleep 2

# Verify fix worked
NEW_IFACE=$(route get "$TAILSCALE_PEER" 2>/dev/null | awk '/interface:/{print $2}')

if [[ "$NEW_IFACE" == utun* ]]; then
    printf '{"additionalContext":"[tailscale-route-check] Tailscale OS routes were missing (traffic was routing via %s instead of utun). Auto-fixed with tailscale down/up. Routes now correct via %s."}\n' "$IFACE" "$NEW_IFACE"
else
    printf '{"additionalContext":"[tailscale-route-check] WARNING: Tailscale routes still missing after fix attempt (interface: %s). SSH/HTTP to NUC via Tailscale may be broken — run tailscale down && tailscale up manually if needed."}\n' "$NEW_IFACE"
fi
