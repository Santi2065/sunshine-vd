#!/usr/bin/env bash
# Uninstall sunshine-vd and put everything back the way it was.
#   ./uninstall.sh [--yes]
#
# SPDX-License-Identifier: MIT
set -euo pipefail

BIN="$HOME/.local/bin/sunshine-vd"
CFG_DIR="$HOME/.config/sunshine-vd"
STATE="$CFG_DIR/install.state"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
EDID_NAME="sunshine-vd.bin"
EDID_PATH="/usr/lib/firmware/edid/$EDID_NAME"
DRACUT_CONF="/etc/dracut.conf.d/90-sunshine-vd.conf"
DEFAULT_UNIT="app-dev.lizardbyte.app.Sunshine.service"
PROC_CMDLINE="${VD_PROC_CMDLINE:-/proc/cmdline}"
# Prefer the copy shipped with this script (it knows every subcommand used here).
TOOL="$HERE/sunshine-vd"; [ -f "$TOOL" ] || TOOL="$BIN"

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; }
state_get() { [ -f "$STATE" ] && sed -n "s/^$1=//p" "$STATE" | tail -1 || true; }
state_has() { [ -f "$STATE" ] && grep -q "^$1=" "$STATE"; }

[ "$(id -u)" -ne 0 ] || { echo "Run this as your normal user, not with sudo." >&2; exit 1; }
[ -f "$STATE" ] || warn "$STATE not found; undoing whatever is found"

if [ "${1:-}" != "--yes" ]; then
  read -r -p "Uninstall sunshine-vd? [y/N] " ans
  [[ "$ans" =~ ^[yYsS]$ ]] || { echo "Cancelled."; exit 0; }
fi

# 1) Kernel parameters first: the part that matters most. Look for every
#    connector we may have used: install state, running kernel, boot entries.
CONNS="$( { state_get CONNECTOR
            { cat "$PROC_CMDLINE" 2>/dev/null; sudo grubby --info=ALL 2>/dev/null || true; } \
              | grep -o 'drm\.edid_firmware=[^: "]*:edid/sunshine-vd\.bin' \
              | sed 's/^drm\.edid_firmware=\([^:]*\):.*/\1/' || true
          } | grep . | sort -u || true)"
for c in $CONNS; do
  sudo grubby --update-kernel=ALL --remove-args="drm.edid_firmware=$c:edid/$EDID_NAME video=$c:e"
  ok "kernel parameters for $c removed"
done
[ -n "$CONNS" ] || warn "no sunshine-vd kernel parameters found"
sudo rm -f "$EDID_PATH" "$DRACUT_CONF"
echo "  rebuilding the initramfs..."
sudo dracut -f --regenerate-all >/dev/null
ok "EDID and initramfs cleaned up"

# 2) If a stream left the virtual display on, restore the displays.
"$PY" "$TOOL" stop >/dev/null 2>&1 || true

# 3) sunshine.conf: drop our global_prep_cmd entry; put back output_name and
#    capture only if we recorded them and they still hold what we set.
SUN_CONF="$("$PY" "$TOOL" conf-path 2>/dev/null || echo "$HOME/.config/sunshine/sunshine.conf")"
if [ -f "$SUN_CONF" ]; then
  cp -p "$SUN_CONF" "$SUN_CONF.bak-uninstall-$(date +%Y%m%d-%H%M%S)"
  args=(sunshine-conf remove --file "$SUN_CONF")
  if state_has PREV_OUTPUT_NAME; then
    args+=(--restore-output "$(state_get PREV_OUTPUT_NAME)")
    if [ -n "$(state_get CONNECTOR)" ]; then args+=(--expect-output "$(state_get CONNECTOR)"); fi
  fi
  if state_has PREV_CAPTURE; then args+=(--restore-capture "$(state_get PREV_CAPTURE)"); fi
  if "$PY" "$TOOL" "${args[@]}"; then
    ok "sunshine.conf restored (backup next to it)"
  else
    warn "could not edit $SUN_CONF: remove the sunshine-vd entry from global_prep_cmd by hand"
  fi
fi

# 4) Login screen (GDM).
if [ "$(state_get GDM_COPIED)" = 1 ]; then
  if [ "$(state_get GDM_BACKUP)" = 1 ]; then
    sudo mv -f /var/lib/gdm/.config/monitors.xml.bak-sunshine-vd /var/lib/gdm/.config/monitors.xml
  else
    sudo rm -f /var/lib/gdm/.config/monitors.xml
  fi
  ok "login screen layout restored"
fi

# 5) User files.
systemctl --user stop sunshine-vd-inhibit >/dev/null 2>&1 || true
rm -f "$BIN"
rm -rf "$CFG_DIR"
ok "helper and settings removed (the log stays in ~/.local/state/sunshine-vd)"

# 6) Restart Sunshine so it stops using the virtual connector.
UNIT=""
for p in /proc/[0-9]*; do
  [ "$(cat "$p/comm" 2>/dev/null)" = sunshine ] || continue
  [ "$(stat -c %u "$p" 2>/dev/null)" = "$(id -u)" ] || continue
  UNIT="$(sed -n 's#.*/\([^/]*\.service\)$#\1#p' "$p/cgroup" 2>/dev/null | tail -1)"
  case "$UNIT" in user@*.service) UNIT="" ;; esac
  [ -n "$UNIT" ] && break
done
if [ -z "$UNIT" ] && systemctl --user cat "$DEFAULT_UNIT" >/dev/null 2>&1; then UNIT="$DEFAULT_UNIT"; fi
if [ -n "$UNIT" ] && systemctl --user restart "$UNIT" >/dev/null 2>&1; then
  ok "Sunshine restarted ($UNIT)"
else
  warn "restart Sunshine yourself"
fi
echo
echo "Done. Reboot now (before installing kernel updates) so the kernel stops"
echo "forcing the virtual connector."
