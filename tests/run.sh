#!/usr/bin/env bash
# Run every check: linters, unit tests, the helper against a fake GNOME, and
# the installer simulation. Needs python3-gobject and dbus (dbus-run-session).
# Optional (used when installed): the shellcheck and pyflakes linters, edid-decode.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY="${PYTHON:-python3}"
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "shellcheck"
if command -v shellcheck >/dev/null; then
  shellcheck -S warning install.sh uninstall.sh tests/*.sh && echo "ok"
else
  echo "skipped (shellcheck not installed)"
fi

step "pyflakes"
if "$PY" -m pyflakes --version >/dev/null 2>&1; then
  "$PY" -m pyflakes sunshine-vd tests/*.py && echo "ok"
else
  echo "skipped (pyflakes not installed)"
fi

step "unit tests (EDID, mode selection, sunshine.conf, connectors)"
"$PY" tests/test_units.py

step "helper against a fake GNOME (D-Bus)"
dbus-run-session -- "$PY" tests/test_helper.py 2>&1 | grep -v 'Failed to set fd limit' || exit 1

step "installer simulation"
PYTHON="$PY" bash tests/test_install.sh
