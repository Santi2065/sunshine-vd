#!/usr/bin/env bash
# Installer/uninstaller simulation: fake sysfs and kernel command line, stub
# sudo/grubby/dracut/systemctl/rpm. Nothing on the real system is touched.
# Must run as a normal user (the installer refuses root).
# shellcheck disable=SC2034  # out/conf are read inside check(), via eval
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
if [ "$(id -u)" = 0 ]; then
  echo "SKIP test_install.sh: run it as a normal user (the installer refuses root)"
  exit 0
fi

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/home/.config/sunshine" "$T/sys/card1/device"
echo 0x10de > "$T/sys/card1/device/vendor"
for c in DP-1:connected DP-2:disconnected DP-3:disconnected HDMI-A-1:disconnected Writeback-1:unknown; do
  mkdir -p "$T/sys/card1-${c%%:*}"
  echo "${c##*:}" > "$T/sys/card1-${c%%:*}/status"
  echo disabled > "$T/sys/card1-${c%%:*}/enabled"
done
echo "BOOT_IMAGE=/vmlinuz ro rhgb quiet" > "$T/cmdline"

stub() { printf '#!/bin/sh\necho "%s $*" >> "%s/calls.log"\n%s\n' "$1" "$T" "${2:-exit 0}" > "$T/bin/$1"; chmod +x "$T/bin/$1"; }
stub sudo 'exit 0'
stub grubby
stub dracut
stub systemd-run
stub gnome-session-inhibit
stub systemctl
stub flatpak 'exit 1'
stub rpm 'echo Sunshine-0.0.0-1.fc45.x86_64; exit 0'
printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v "$PY")" > "$T/bin/python3"; chmod +x "$T/bin/python3"

ORIG='global_prep_cmd = [{"do":"/usr/local/bin/wake on","undo":"/usr/local/bin/wake off"}]'
printf 'origin_web_ui_allowed = pc\noutput_name = 0\n%s\n' "$ORIG" > "$T/home/.config/sunshine/sunshine.conf"

export HOME="$T/home" PATH="$T/bin:$PATH" PYTHON=python3
export VD_SYSFS_DRM="$T/sys" VD_PROC_CMDLINE="$T/cmdline" VD_EDID_PATH="$T/firmware/edid/sunshine-vd.bin"
export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=GNOME

fails=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fails=$((fails + 1)); fi; }
calls() { cat "$T/calls.log" 2>/dev/null || true; }
reset_calls() { : > "$T/calls.log"; }

# 1) --check changes nothing
reset_calls
out="$(bash "$ROOT/install.sh" --check 2>&1)"
check "--check picks the highest free DP" '[[ "$out" == *"using DP-3"* ]]'
check "--check keeps the user prep command" '[[ "$out" == *"/usr/local/bin/wake on"* ]]'
check "--check calls no sudo" '! calls | grep -q "^sudo"'
check "--check writes nothing" '[ ! -e "$HOME/.config/sunshine-vd" ]'

# 2) refuses an occupied connector and invalid modes
out="$(VD_CONNECTOR=DP-1 bash "$ROOT/install.sh" --check 2>&1 || true)"
check "refuses a connector with a monitor plugged in" '[[ "$out" == *"real monitor plugged in"* ]]'
out="$(VD_CONNECTOR=DP-9 bash "$ROOT/install.sh" --check 2>&1 || true)"
check "refuses a connector that does not exist" '[[ "$out" == *"does not exist"* ]]'
out="$(MODES="4000x2400@144" bash "$ROOT/install.sh" --check 2>&1 || true)"
check "refuses invalid MODES" '[[ "$out" == *"invalid MODES"* ]]'

echo "BOOT_IMAGE=/vmlinuz ro video=efifb:off" > "$T/cmdline"
out="$(bash "$ROOT/install.sh" --check 2>&1 || true)"
check "refuses to clobber an existing video= argument" '[[ "$out" == *"already has video=efifb:off"* ]]'
echo "BOOT_IMAGE=/vmlinuz ro rhgb quiet" > "$T/cmdline"

cp "$HOME/.config/sunshine/sunshine.conf" "$T/conf.good"
printf 'global_prep_cmd = [{"do": "x"\n' > "$HOME/.config/sunshine/sunshine.conf"
reset_calls
out="$(bash "$ROOT/install.sh" --yes 2>&1 || true)"
check "unparseable global_prep_cmd stops before any sudo step" '[[ "$out" == *"fix global_prep_cmd"* ]] && ! calls | grep -q "^sudo"'
cp "$T/conf.good" "$HOME/.config/sunshine/sunshine.conf"

# 3) install
reset_calls
bash "$ROOT/install.sh" --yes > "$T/install.out" 2>&1 || { cat "$T/install.out"; exit 1; }
conf="$(cat "$HOME/.config/sunshine/sunshine.conf")"
check "kernel parameters added for DP-3" 'calls | grep -q "grubby --update-kernel=ALL --args=drm.edid_firmware=DP-3:edid/sunshine-vd.bin video=DP-3:e"'
check "initramfs rebuilt" 'calls | grep -q "sudo dracut -f --regenerate-all"'
check "EDID installed" 'calls | grep -q "sudo install -D -m 0644 .*sunshine-vd.bin $VD_EDID_PATH"'
check "sunshine.conf keeps the user command first" '[[ "$conf" == *"/usr/local/bin/wake on"*"sunshine-vd start"* ]]'
check "sunshine.conf: capture = kms, output_name = DP-3" '[[ "$conf" == *"capture = kms"* && "$conf" == *"output_name = DP-3"* ]]'
check "sunshine.conf backed up" 'ls "$HOME/.config/sunshine/" | grep -q "sunshine.conf.bak-sunshine-vd-"'
check "helper installed" '[ -x "$HOME/.local/bin/sunshine-vd" ]'
check "settings written" 'grep -q "^CONNECTOR=DP-3$" "$HOME/.config/sunshine-vd/config"'
check "previous output_name remembered" 'grep -q "^PREV_OUTPUT_NAME=0$" "$HOME/.config/sunshine-vd/install.state"'

# 4) reinstall with custom modes: idempotent, modes remembered
reset_calls
sleep 1
MODES="1696x1200@60,1696x1200@120" bash "$ROOT/install.sh" --yes > "$T/install2.out" 2>&1 || { cat "$T/install2.out"; exit 1; }
conf="$(cat "$HOME/.config/sunshine/sunshine.conf")"
check "reinstall: only one sunshine-vd entry" '[ "$(grep -o "sunshine-vd start" <<< "$conf" | wc -l)" = 1 ]'
check "reinstall: custom modes remembered" 'grep -q "^MODES=1696x1200@60,1696x1200@120$" "$HOME/.config/sunshine-vd/install.state"'
check "reinstall: previous output_name not overwritten" 'grep -q "^PREV_OUTPUT_NAME=0$" "$HOME/.config/sunshine-vd/install.state"'
out="$(bash "$ROOT/install.sh" --check 2>&1)"
check "next --check reuses the remembered modes" '[[ "$out" == *"1696x1200@120"* ]]'

# 5) uninstall restores everything
reset_calls
bash "$ROOT/uninstall.sh" --yes > "$T/uninstall.out" 2>&1 || { cat "$T/uninstall.out"; exit 1; }
conf="$(cat "$HOME/.config/sunshine/sunshine.conf")"
check "uninstall: kernel parameters removed" 'calls | grep -q "grubby --update-kernel=ALL --remove-args=drm.edid_firmware=DP-3:edid/sunshine-vd.bin video=DP-3:e"'
check "uninstall: EDID and dracut config removed" 'calls | grep -q "sudo rm -f $VD_EDID_PATH /etc/dracut.conf.d/90-sunshine-vd.conf"'
check "uninstall: user command kept, ours removed" '[[ "$conf" == *"/usr/local/bin/wake on"* && "$conf" != *"sunshine-vd"* ]]'
check "uninstall: output_name restored, capture removed" '[[ "$conf" == *"output_name = 0"* && "$conf" != *"capture"* ]]'
check "uninstall: helper and settings removed" '[ ! -e "$HOME/.local/bin/sunshine-vd" ] && [ ! -e "$HOME/.config/sunshine-vd" ]'

# 6) a second uninstall (no state left) must not touch the user's settings
printf 'output_name = 1\ncapture = nvfbc\n' > "$HOME/.config/sunshine/sunshine.conf"
bash "$ROOT/uninstall.sh" --yes > "$T/uninstall2.out" 2>&1 || { cat "$T/uninstall2.out"; exit 1; }
check "second uninstall keeps output_name and capture" '[ "$(cat "$HOME/.config/sunshine/sunshine.conf")" = "$(printf "output_name = 1\ncapture = nvfbc")" ]'

# 7) uninstall without state still finds the parameters of the running kernel
echo "BOOT_IMAGE=/vmlinuz ro drm.edid_firmware=DP-2:edid/sunshine-vd.bin video=DP-2:e" > "$T/cmdline"
reset_calls
bash "$ROOT/uninstall.sh" --yes > "$T/uninstall3.out" 2>&1 || { cat "$T/uninstall3.out"; exit 1; }
check "uninstall without state removes DP-2 from the running kernel's cmdline" 'calls | grep -q "remove-args=drm.edid_firmware=DP-2:edid/sunshine-vd.bin video=DP-2:e"'

echo
if [ "$fails" = 0 ]; then echo "ALL PASSED"; else echo "$fails FAILED"; exit 1; fi
