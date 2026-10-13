#!/usr/bin/env bash
# sunshine-vd installer — Fedora (grubby + dracut), GNOME on Wayland.
#
#   ./install.sh --check    show what would be done; changes nothing
#   ./install.sh            install (asks for confirmation and your sudo password)
#   ./install.sh --finish   AFTER rebooting: keep the virtual display off outside
#                           streams, copy that layout to the login screen (GDM),
#                           restart Sunshine and run diagnostics
#
# Optional environment variables:
#   VD_CONNECTOR=DP-3          connector to use (default: highest-numbered free DP)
#   MODES="1920x1080@60,..."   EDID modes; the first one is the preferred mode
#   SUNSHINE_CONF=path         Sunshine config (default: ~/.config/sunshine/sunshine.conf)
#
# SPDX-License-Identifier: MIT
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_BIN="$HERE/sunshine-vd"
BIN="$HOME/.local/bin/sunshine-vd"
CFG_DIR="$HOME/.config/sunshine-vd"
CFG="$CFG_DIR/config"
STATE="$CFG_DIR/install.state"
SUN_CONF="${SUNSHINE_CONF:-$( (sed -n 's/^SUNSHINE_CONF=//p' "$CFG" 2>/dev/null || true) | tail -1)}"
SUN_CONF="${SUN_CONF:-$HOME/.config/sunshine/sunshine.conf}"
SUN_CONF="${SUN_CONF/#\~/$HOME}"
DEFAULT_UNIT="app-dev.lizardbyte.app.Sunshine.service"
EDID_NAME="sunshine-vd.bin"
EDID_PATH="/usr/lib/firmware/edid/$EDID_NAME"
DRACUT_CONF="/etc/dracut.conf.d/90-sunshine-vd.conf"
PROC_CMDLINE="${VD_PROC_CMDLINE:-/proc/cmdline}"
PY="${PYTHON:-python3}"

MODE="install"
ASSUME_YES=0
for a in "$@"; do
  case "$a" in
    --check) MODE="check" ;;
    --finish) MODE="finish" ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; }
die()  { printf '\n\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }
helper() { "$PY" "$SRC_BIN" "$@"; }

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  local ans
  read -r -p "$1 [y/N] " ans
  [[ "$ans" =~ ^[yYsS]$ ]]
}

state_get() { [ -f "$STATE" ] && sed -n "s/^$1=//p" "$STATE" | tail -1 || true; }
state_set() {
  mkdir -p "$CFG_DIR"
  touch "$STATE"
  grep -v "^$1=" "$STATE" > "$STATE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$STATE.tmp"
  mv "$STATE.tmp" "$STATE"
}

# The systemd unit a process runs in: the last cgroup path component, only if
# it is a .service. A Sunshine started from a terminal lives in a .scope (and
# under user@UID.service), which must not be mistaken for its unit.
unit_from_cgroup() {
  local u
  u="$(sed -n 's#.*/\([^/]*\.service\)$#\1#p' "$1" 2>/dev/null | tail -1)"
  case "$u" in
    ""|user@*.service) echo "(no-unit)" ;;
    *) echo "$u" ;;
  esac
}

# Sunshine processes of this user and the systemd units they run in.
sunshine_units() {
  local p uid
  uid="$(id -u)"
  for p in /proc/[0-9]*; do
    [ "$(cat "$p/comm" 2>/dev/null)" = sunshine ] || continue
    [ "$(stat -c %u "$p" 2>/dev/null)" = "$uid" ] || continue
    unit_from_cgroup "$p/cgroup"
  done
}

detect_sunshine_unit() {
  local units n
  units="$(sunshine_units | sort -u)"
  n="$(printf '%s' "$units" | grep -c . || true)"
  if [ "$n" -gt 1 ]; then
    warn "several Sunshine instances are running ($(echo "$units" | xargs)). Only one can own the"
    warn "ports; disable the extra one, e.g.: systemctl --user disable --now <unit>"
  fi
  SUN_UNIT="$(printf '%s\n' "$units" | grep -v '^(no-unit)$' | head -1 || true)"
  if [ -z "$SUN_UNIT" ] && systemctl --user cat "$DEFAULT_UNIT" >/dev/null 2>&1; then
    SUN_UNIT="$DEFAULT_UNIT"
  fi
}

restart_sunshine() {
  if [ -n "${SUN_UNIT:-}" ]; then
    systemctl --user restart "$SUN_UNIT" && ok "Sunshine restarted ($SUN_UNIT)" \
      || warn "could not restart $SUN_UNIT; restart Sunshine yourself"
  else
    warn "Sunshine is not running as a systemd user service: restart it yourself"
  fi
}

# ------------------------------------------------------------------ checks
preflight() {
  bold "1) Checking the system"
  local bad=0
  if [ "$(id -u)" -ne 0 ]; then
    ok "running as $(id -un) (sudo is only used for the system-wide steps)"
  else
    fail "do not run this with sudo: run it as your normal user"; bad=1
  fi
  if [ -e /run/ostree-booted ]; then
    fail "atomic system (Silverblue/Bazzite/...): not supported yet (needs rpm-ostree)"; bad=1
  fi
  if [ -r /etc/os-release ] && grep -q '^ID=fedora' /etc/os-release; then
    ok "Fedora $(sed -n 's/^VERSION_ID=//p' /etc/os-release)"
  else
    warn "this does not look like Fedora; the installer needs grubby + dracut (see docs for manual steps)"
  fi
  [ "${XDG_SESSION_TYPE:-}" = wayland ] && ok "Wayland session" || warn "session type '${XDG_SESSION_TYPE:-?}' (expected wayland)"
  [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] && ok "GNOME" || warn "desktop '${XDG_CURRENT_DESKTOP:-?}' (this tool drives GNOME/Mutter)"
  if rpm -q Sunshine >/dev/null 2>&1 || rpm -q sunshine >/dev/null 2>&1; then
    ok "Sunshine installed as an RPM ($(rpm -q Sunshine 2>/dev/null || rpm -q sunshine))"
  elif flatpak list 2>/dev/null | grep -i sunshine >/dev/null; then
    fail "Sunshine is a Flatpak: KMS capture does not work from Flatpak. Install the RPM."; bad=1
  else
    warn "Sunshine RPM not found (fine if you built it yourself; it needs KMS capture)"
  fi
  if "$PY" -c 'import gi; gi.require_version("Gio","2.0"); from gi.repository import Gio' 2>/dev/null; then
    ok "python3-gobject"
  else
    fail "python3-gobject is missing:  sudo dnf install python3-gobject"; bad=1
  fi
  if [ -e "$SUN_CONF" ] && [ ! -w "$SUN_CONF" ]; then
    fail "cannot write $SUN_CONF (owned by root?)"; bad=1
  fi
  if [ -e "$SUN_CONF" ]; then
    if helper sunshine-conf check --file "$SUN_CONF"; then
      ok "sunshine.conf: $SUN_CONF"
    else
      fail "fix global_prep_cmd in $SUN_CONF first (see the error above)"; bad=1
    fi
  fi
  local t
  for t in grubby dracut systemd-run; do
    command -v "$t" >/dev/null && ok "$t" || { fail "$t is missing"; bad=1; }
  done
  command -v gnome-session-inhibit >/dev/null && ok "gnome-session-inhibit" \
    || warn "gnome-session-inhibit is missing: GNOME may blank the screen during long streams"
  detect_sunshine_unit
  [ -n "${SUN_UNIT:-}" ] && ok "Sunshine service: $SUN_UNIT" || warn "no Sunshine systemd user service found"
  [ "$bad" = 0 ] || die "fix the items above and run the installer again"
}

# ------------------------------------------------------- choose connector
pick_connector() {
  bold "2) Choosing the connector for the virtual display"
  helper connectors | sed 's/^/  /' || true
  local forced prev rc=0
  forced="$(sed -n 's/.*drm\.edid_firmware=\([^:]*\):edid\/sunshine-vd\.bin.*/\1/p' "$PROC_CMDLINE")"
  prev="$(state_get CONNECTOR)"
  if [ -n "${VD_CONNECTOR:-}" ]; then CONN="$VD_CONNECTOR"
  elif [ -n "$prev" ]; then CONN="$prev"
  elif [ -n "$forced" ]; then CONN="$forced"
  else CONN="$(helper connectors --pick || true)"
  fi
  [ -n "${CONN:-}" ] || die "no free DisplayPort/HDMI connector found on the GPU"
  helper connectors --validate "$CONN" || rc=$?
  case "$rc" in
    0) ;;
    2) die "connector $CONN does not exist" ;;
    3) die "$CONN has a real monitor plugged in; pick another one with VD_CONNECTOR=..." ;;
    4) die "$CONN exists on more than one GPU and the kernel parameters would apply to all of them; pick another one with VD_CONNECTOR=..." ;;
    *) die "could not validate $CONN" ;;
  esac
  if [ "$CONN" != "$forced" ] && [ "$CONN" != "$prev" ] \
     && grep -q "<connector>$CONN</connector>" "$HOME/.config/monitors.xml" 2>/dev/null; then
    if [ -n "${VD_CONNECTOR:-}" ]; then
      warn "GNOME remembers a monitor on $CONN: make sure that port is physically empty"
    else
      die "GNOME remembers a monitor on $CONN (a monitor that is off can look disconnected). If that port is really empty, run again with VD_CONNECTOR=$CONN"
    fi
  fi
  local vendor
  vendor="$(helper connectors --json | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(next((c["vendor"] for c in d["connectors"] if c["name"]==sys.argv[1]), "?"))' "$CONN")"
  ok "using $CONN ($vendor GPU); do not plug a monitor into that port while installed"
  if [ "$vendor" != NVIDIA ]; then
    warn "only tested on NVIDIA. AMD/Intel should work the same way but are untested:"
    warn "please report how it went (GitHub issue: 'Compatibility report')"
  fi
}

check_foreign_args() {
  local sources ours other
  sources="$(cat "$PROC_CMDLINE" /etc/kernel/cmdline /etc/default/grub 2>/dev/null || true)
$(grubby --info=ALL 2>/dev/null | grep '^args=' || true)"
  other="$(grep -o 'drm\.edid_firmware=[^ "]*' <<< "$sources" | grep -v 'sunshine-vd\.bin' | sort -u || true)"
  [ -z "$other" ] || die "another EDID override is already configured ($(echo "$other" | xargs)); remove it first"
  # grubby --args=video=... REPLACES every existing video= argument, so refuse
  # rather than silently dropping the user's own (e.g. video=efifb:off).
  ours="$(grep -o 'drm\.edid_firmware=[^: "]*:edid/sunshine-vd\.bin' <<< "$sources" \
    | sed 's/drm\.edid_firmware=\([^:]*\):.*/video=\1:e/' | sort -u || true)"
  other="$(grep -o 'video=[^ "]*' <<< "$sources" | sort -u \
    | grep -vxF -f <(printf '%s\n' "video=$CONN:e" "$ours") || true)"
  [ -z "$other" ] || die "your kernel command line already has $(echo "$other" | xargs). grubby would replace it with ours, so the installer stops here. See docs/how-it-works.md#manual-installation to combine them by hand."
}

resolve_modes() {
  # MODES from the environment > modes used last time > keep an EDID that is
  # already installed > defaults.
  if [ "${MODES:-}" = default ]; then MODES=""; MODES_SRC="default"
  elif [ -n "${MODES:-}" ]; then MODES_SRC="env"
  elif [ -n "$(state_get MODES)" ]; then MODES="$(state_get MODES)"; MODES_SRC="state"
  elif [ "$(head -c 8 "$EDID_PATH" 2>/dev/null | od -An -tx1 | tr -d ' \n')" = 00ffffffffffff00 ] \
       && [ "$(stat -c %s "$EDID_PATH" 2>/dev/null)" = 256 ]; then MODES=""; MODES_SRC="keep"
  else MODES=""; MODES_SRC="default"
  fi
  if [ "$MODES_SRC" != keep ]; then
    helper make-edid ${MODES:+--modes "$MODES"} --out /dev/null >/dev/null \
      || die "invalid MODES (see the error above)"
  fi
}

show_plan() {
  bold "3) Plan"
  echo "  System-wide (sudo):"
  if [ "$MODES_SRC" = keep ]; then
    echo "    - keep the EDID already installed at $EDID_PATH (set MODES=... to replace it)"
  else
    echo "    - virtual-display EDID at $EDID_PATH with these modes:"
    helper make-edid ${MODES:+--modes "$MODES"} --out /dev/null | sed 1d | sed 's/^/      /'
  fi
  cat <<EOF
    - add it to the initramfs ($DRACUT_CONF) and rebuild it
    - kernel parameters: drm.edid_firmware=$CONN:edid/$EDID_NAME video=$CONN:e
  Your user:
    - $BIN and $CFG
    - $SUN_CONF: global_prep_cmd (start/stop), capture = kms, output_name = $CONN
      (backed up next to it; uninstall.sh restores the previous values)
EOF
  local prev
  prev="$(helper conf-get global_prep_cmd --file "$SUN_CONF")"
  if [ -n "$prev" ]; then
    echo "      your existing prep commands are kept and run before sunshine-vd:"
    echo "      $prev"
  fi
  echo "  Then: REBOOT and run ./install.sh --finish"
}

# ---------------------------------------------------------------- install
TMPD=""
cleanup() { [ -n "$TMPD" ] && rm -rf "$TMPD"; return 0; }
trap cleanup EXIT

do_install() {
  TMPD="$(mktemp -d)"
  bold "4) Installing"
  if [ "$MODES_SRC" != keep ]; then
    helper make-edid ${MODES:+--modes "$MODES"} --out "$TMPD/$EDID_NAME" >/dev/null
    [ "$(stat -c %s "$TMPD/$EDID_NAME")" = 256 ] || die "the generated EDID is not 256 bytes"
    sudo install -D -m 0644 "$TMPD/$EDID_NAME" "$EDID_PATH"
    if command -v restorecon >/dev/null; then sudo restorecon -q "$EDID_PATH" || true; fi
    ok "EDID written to $EDID_PATH"
    state_set MODES "$MODES"   # empty for the defaults
  else
    ok "keeping the existing EDID"
  fi

  printf 'install_items+=" %s "\n' "$EDID_PATH" | sudo tee "$DRACUT_CONF" >/dev/null
  echo "  rebuilding the initramfs (this can take a couple of minutes)..."
  sudo dracut -f --regenerate-all >/dev/null
  ok "initramfs rebuilt"

  local old k
  old="$(state_get CONNECTOR)"
  # Record the connector first, so uninstall.sh can clean up even if this
  # script is interrupted while editing the boot entries.
  state_set CONNECTOR "$CONN"
  if [ -n "$old" ] && [ "$old" != "$CONN" ]; then
    sudo grubby --update-kernel=ALL --remove-args="drm.edid_firmware=$old:edid/$EDID_NAME video=$old:e"
  fi
  sudo grubby --update-kernel=ALL --args="drm.edid_firmware=$CONN:edid/$EDID_NAME video=$CONN:e"
  # Keep the rescue entry clean: a known-good way to boot without the virtual display.
  for k in /boot/vmlinuz-0-rescue-*; do
    [ -e "$k" ] || continue
    sudo grubby --update-kernel="$k" --remove-args="drm.edid_firmware=$CONN:edid/$EDID_NAME video=$CONN:e"
  done
  ok "kernel parameters added (every boot entry except rescue)"

  install -D -m 0755 "$SRC_BIN" "$BIN"
  mkdir -p "$CFG_DIR"
  if [ -f "$CFG" ]; then
    sed -i "s/^CONNECTOR=.*/CONNECTOR=$CONN/" "$CFG"
    grep -q '^CONNECTOR=' "$CFG" || echo "CONNECTOR=$CONN" >> "$CFG"
    if [ -n "${SUNSHINE_CONF:-}" ]; then
      sed -i '/^SUNSHINE_CONF=/d' "$CFG"
      echo "SUNSHINE_CONF=$SUNSHINE_CONF" >> "$CFG"
    fi
  else
    cat > "$CFG" <<EOF
# sunshine-vd settings (changes apply on the next stream)
CONNECTOR=$CONN
# true: only the virtual display while streaming (your monitors turn off)
# false: the virtual display is added to the right of your monitors
DISABLE_PHYSICAL=true
# auto = 1 below 2000 px of height, 2 from 2000 px (e.g. 3840x2160)
SCALE=auto
WAKE_DISPLAYS=true
INHIBIT_IDLE=true
SETTLE_SECONDS=1.5
SUNSHINE_CONF=${SUNSHINE_CONF:-}
EOF
  fi
  ok "helper at $BIN, settings at $CFG"

  if [ -z "$(state_get INSTALLED_AT)" ]; then
    state_set PREV_OUTPUT_NAME "$(helper conf-get output_name --file "$SUN_CONF")"
    state_set PREV_CAPTURE "$(helper conf-get capture --file "$SUN_CONF")"
    state_set INSTALLED_AT "$(date -Iseconds)"
  fi
  if [ -f "$SUN_CONF" ]; then
    cp -p "$SUN_CONF" "$SUN_CONF.bak-sunshine-vd-$(date +%Y%m%d-%H%M%S)"
  fi
  helper sunshine-conf add --file "$SUN_CONF" --bin "$BIN" --connector "$CONN"
  ok "sunshine.conf updated (backup next to it)"
  if "$BIN" save-layout >/dev/null 2>&1; then
    ok "current display layout saved (restored by --finish)"
  else
    warn "could not save the current display layout (--finish will use GNOME's)"
  fi

  echo
  bold "First part done."
  cat <<EOF
  Next:
    1. Reboot.
    2. Open a terminal in this folder and run:   ./install.sh --finish
       (GNOME will ask whether to keep the display settings: KEEP CHANGES)

  Until --finish runs, GNOME treats the virtual display as a real monitor:
  - if the login screen is not on your monitor, log in blind: press Enter,
    type your password and press Enter again;
  - if the mouse wanders off the edge of the screen, that is the virtual display.
  --finish turns it off. To undo everything: ./uninstall.sh
  Rescue: the "rescue" boot entry and the GRUB 'e' editor both work without it
  (see docs/troubleshooting.md).
EOF
}

# ------------------------------------------------------------------ finish
do_finish() {
  local conn st
  conn="$(state_get CONNECTOR)"
  [ -n "$conn" ] || die "no previous installation found (run ./install.sh first)"
  bold "Finishing the installation (connector $conn)"
  grep -q "video=$conn:e" "$PROC_CMDLINE" || die "the running kernel does not have the parameters: did you reboot?"
  ok "kernel parameters active"
  st="$(helper connectors --json | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(next((c["status"] for c in d["connectors"] if c["name"]==sys.argv[1]), "missing"))' "$conn")"
  [ "$st" = connected ] && ok "the kernel sees $conn as connected" \
    || die "the kernel sees $conn as '$st': the EDID did not load (check: sudo dmesg | grep -i edid)"
  "$BIN" status || true

  echo
  bold "Keeping the virtual display OFF outside streams"
  echo "  GNOME will ask \"Keep these display settings?\" -> choose KEEP CHANGES"
  "$BIN" idle || die "it was not saved; run ./install.sh --finish again"

  if id gdm >/dev/null 2>&1 && [ -f "$HOME/.config/monitors.xml" ]; then
    echo
    bold "Copying this display layout to the login screen (GDM)"
    if confirm "  Copy ~/.config/monitors.xml to GDM? (otherwise the login screen may appear on the virtual display)"; then
      if [ "$(state_get GDM_COPIED)" != 1 ]; then
        # First copy: back up GDM's own file, if it had one (only once).
        if sudo test -f /var/lib/gdm/.config/monitors.xml; then
          sudo cp -p /var/lib/gdm/.config/monitors.xml /var/lib/gdm/.config/monitors.xml.bak-sunshine-vd
          state_set GDM_BACKUP 1
        else
          state_set GDM_BACKUP 0
        fi
      fi
      sudo test -d /var/lib/gdm/.config || sudo install -d -o gdm -g gdm -m 0700 /var/lib/gdm/.config
      sudo install -o gdm -g gdm -m 0644 "$HOME/.config/monitors.xml" /var/lib/gdm/.config/monitors.xml
      if command -v restorecon >/dev/null; then sudo restorecon -q /var/lib/gdm/.config/monitors.xml || true; fi
      state_set GDM_COPIED 1
      ok "login screen configured"
    fi
  fi

  echo
  detect_sunshine_unit
  restart_sunshine
  sleep 6
  echo
  "$BIN" doctor || true
  cat <<EOF

  Try it: connect from Moonlight/Artemis to "Desktop". Your monitor turns off and
  the client gets the desktop at its own resolution. To go back, quit the app from
  the client (Quit), do not just disconnect.

  If you are ever left without a picture on your monitor:
    - from a terminal (or over SSH):  sunshine-vd stop
    - or press Super+P in GNOME to cycle display layouts
  Log: ~/.local/state/sunshine-vd/sunshine-vd.log
EOF
}

# -------------------------------------------------------------------- main
case "$MODE" in
  finish)
    do_finish ;;
  check)
    preflight; pick_connector; check_foreign_args; resolve_modes; show_plan
    echo; echo "(--check: nothing was changed)" ;;
  install)
    preflight; pick_connector; check_foreign_args; resolve_modes; show_plan
    echo
    confirm "Proceed with the installation?" || { echo "Cancelled, nothing was changed."; exit 0; }
    do_install ;;
esac
