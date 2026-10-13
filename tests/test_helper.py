#!/usr/bin/env python3
"""End-to-end tests: the real sunshine-vd helper against a fake GNOME.

Run inside a private session bus:
    dbus-run-session -- python3 tests/test_helper.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "sunshine-vd"
MOCK = ROOT / "tests" / "mock_mutter.py"
PY = sys.executable

if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
    sys.exit("run this under dbus-run-session (see tests/run.sh)")

tmp = Path(tempfile.mkdtemp(prefix="sunshine-vd-test-"))
HOME = tmp / "home"
RUN = tmp / "run"
HOME.mkdir()
RUN.mkdir(mode=0o700)
STATE = tmp / "mock.json"
SYSFS = tmp / "sys"
# Stub systemctl/systemd-run/gnome-session-inhibit: record calls, touch nothing.
STUBS = tmp / "bin"
STUBS.mkdir()
CALLS = tmp / "calls.log"
for tool, rc in (("systemctl", "case \"$*\" in *is-active*) exit 3;; esac; exit 0"),
                 ("systemd-run", "exit 0"), ("gnome-session-inhibit", "exit 0")):
    f = STUBS / tool
    f.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{CALLS}"\n{rc}\n')
    f.chmod(0o755)
ENV = dict(os.environ, HOME=str(HOME), XDG_RUNTIME_DIR=str(RUN), MOCK_STATE=str(STATE),
           VD_SYSFS_DRM=str(SYSFS), VD_PROC_CMDLINE=str(tmp / "cmdline"),
           PATH=f"{STUBS}:{os.environ.get('PATH', '/usr/bin:/bin')}")
VIRT = "DP-3"
PHYS = "DP-1"


def mid(w, h, r):
    return f"{w}x{h}@{r:.3f}"


def physical_modes():
    return [
        {"id": mid(2560, 1440, 165.0), "w": 2560, "h": 1440, "r": 165.0, "preferred": True},
        {"id": mid(2560, 1440, 144.0), "w": 2560, "h": 1440, "r": 144.0},
        {"id": mid(2560, 1440, 59.951), "w": 2560, "h": 1440, "r": 59.951},
        {"id": mid(1920, 1080, 60.0), "w": 1920, "h": 1080, "r": 60.0},
    ]


def virtual_modes():
    # What GNOME offers for the EDID built from a tablet-oriented MODES list.
    table = [(1696, 1200, 60.000175, True), (1696, 1200, 120.001221, False),
             (1696, 1200, 143.99937, False), (3392, 2400, 59.999626, False),
             (2560, 1440, 60.000199, False), (2560, 1440, 120.0, False),
             (2400, 1080, 60.000141, False), (2400, 1080, 120.001093, False),
             (1920, 1080, 60.0, False), (1920, 1080, 120.0, False),
             (3840, 2160, 60.0, False), (1280, 720, 60.0, False),
             (640, 480, 59.94, False)]
    return [{"id": mid(w, h, r), "w": w, "h": h, "r": r, "preferred": pref,
             "scales": [1.0, 2.0] if h < 2000 else [1.0, 2.0, 3.0]}
            for (w, h, r, pref) in table]


def fresh_state(virtual_on=True):
    st = {
        "serial": 7, "layout_mode": 1, "power_save": 0,
        "monitors": [
            {"connector": PHYS, "vendor": "ACM", "product": "Desk Monitor", "serial": "123",
             "name": "Desk Monitor 27\"", "modes": physical_modes(), "current": mid(2560, 1440, 165.0)},
            {"connector": VIRT, "vendor": "LNX", "product": "Sunshine VD", "serial": "0x00000001",
             "name": "Sunshine VD", "modes": virtual_modes(),
             "current": mid(1696, 1200, 60.000175) if virtual_on else None},
        ],
        "logical": [{"x": 0, "y": 0, "scale": 1.0, "transform": 0, "primary": True, "connectors": [PHYS]}],
    }
    if virtual_on:
        st["logical"].append({"x": 2560, "y": 0, "scale": 1.0, "transform": 0, "primary": False,
                              "connectors": [VIRT]})
    STATE.write_text(json.dumps(st))


def st():
    return json.loads(STATE.read_text())


def edit(fn):
    s = st()
    fn(s)
    STATE.write_text(json.dumps(s))


def run(*args, env=None):
    e = dict(ENV)
    e.update(env or {})
    return subprocess.run([PY, str(HELPER), *args], env=e, capture_output=True, text=True, timeout=60)


def active():
    s = st()
    out = {}
    for lm in s["logical"]:
        for c in lm["connectors"]:
            m = next(m for m in s["monitors"] if m["connector"] == c)
            out[c] = (m["current"], lm["scale"], lm["primary"], lm["x"], lm["y"])
    return out


def client(w, h, fps, name="Tablet"):
    return {"SUNSHINE_CLIENT_WIDTH": str(w), "SUNSHINE_CLIENT_HEIGHT": str(h),
            "SUNSHINE_CLIENT_FPS": str(fps), "SUNSHINE_CLIENT_NAME": name}


def write_config(extra=""):
    (cfg_dir / "config").write_text(f"CONNECTOR={VIRT}\nSETTLE_SECONDS=0\n{extra}")


failures = 0


def check(name, cond, extra=""):
    global failures
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond:
        failures += 1


PHYS_ONLY = {PHYS: (mid(2560, 1440, 165.0), 1.0, True, 0, 0)}

# ---- setup
cfg_dir = HOME / ".config" / "sunshine-vd"
cfg_dir.mkdir(parents=True)
write_config()
for name, status in ((f"card1-{PHYS}", "connected"), (f"card1-{VIRT}", "connected")):
    (SYSFS / name).mkdir(parents=True)
    (SYSFS / name / "status").write_text(status + "\n")
    (SYSFS / name / "enabled").write_text("enabled\n")
(tmp / "cmdline").write_text(f"ro rhgb drm.edid_firmware={VIRT}:edid/sunshine-vd.bin video={VIRT}:e\n")
fresh_state(virtual_on=True)
mock = subprocess.Popen([PY, str(MOCK)], env=ENV, stdout=subprocess.PIPE, text=True)
assert mock.stdout.readline().strip() == "READY", "mock did not start"
state_file = RUN / "sunshine-vd" / "state.json"

try:
    # 0) first boot after installing: Mutter put the virtual display primary at
    #    x=0 and the monitor to its right at 60 Hz. idle must still work, and
    #    must restore the layout saved before the reboot (165 Hz).
    (cfg_dir / "layout.json").write_text(json.dumps({"layout_mode": 1, "logical": [
        {"x": 0, "y": 0, "scale": 1.0, "transform": 0, "primary": True,
         "monitors": [[PHYS, mid(2560, 1440, 165.0), 2560, 1440, 165.0]]}]}))
    edit(lambda s: s.update(logical=[
        {"x": 0, "y": 0, "scale": 1.0, "transform": 0, "primary": True, "connectors": [VIRT]},
        {"x": 1696, "y": 0, "scale": 1.0, "transform": 0, "primary": False, "connectors": [PHYS]}]))
    edit(lambda s: s["monitors"][0].update(current=mid(2560, 1440, 59.951)))

    # 1) idle: persist a layout with the virtual display off
    r = run("idle", "--no-wait")
    check("idle copes with an offset layout", "Applied your layout from before the reboot" in r.stdout,
          r.stdout + r.stderr)
    check("idle exits 0", r.returncode == 0, r.stdout + r.stderr)
    check("idle uses the persistent method (2)", st()["applied"][-1]["method"] == 2, st().get("applied"))
    check("idle leaves only the physical monitor at 165 Hz", active() == PHYS_ONLY, active())

    # 1b) stop with no stream state and the virtual display off: touch nothing
    edit(lambda s: s["logical"][0].update(transform=1))  # e.g. a rotated monitor
    serial = st()["serial"]
    run("stop")
    check("stop without state leaves the layout alone", st()["serial"] == serial, st()["logical"])
    edit(lambda s: s["logical"][0].update(transform=0))

    # 2) start for a tablet at 1696x1200@120
    r = run("start", env=client(1696, 1200, 120))
    check("start exits 0", r.returncode == 0, r.stderr)
    check("start: only the virtual display, 1696x1200@120, scale 1",
          active() == {VIRT: (mid(1696, 1200, 120.001221), 1.0, True, 0, 0)}, active())
    check("start uses the temporary method (1)", st()["applied"][-1]["method"] == 1)
    check("a snapshot was saved", state_file.exists())
    calls = CALLS.read_text() if CALLS.exists() else ""
    check("start takes an idle inhibitor",
          "systemd-run --user" in calls and "gnome-session-inhibit --inhibit idle:suspend" in calls, calls)

    # 3) a second start keeps the original snapshot
    run("start", env=client(3392, 2400, 60))
    check("2nd start: 3392x2400@60 with scale 2",
          active() == {VIRT: (mid(3392, 2400, 59.999626), 2.0, True, 0, 0)}, active())
    snap = json.loads(state_file.read_text())["snapshot"]
    check("the snapshot still holds the physical layout",
          [m[0] for lm in snap["logical"] for m in lm["monitors"]] == [PHYS], snap)

    # 4) stop restores the physical monitor
    r = run("stop")
    check("stop exits 0", r.returncode == 0, r.stderr)
    check("stop restores the physical monitor at 165 Hz", active() == PHYS_ONLY, active())
    check("stop deletes the runtime state", not state_file.exists())
    check("stop releases the idle inhibitor", "systemctl --user stop sunshine-vd-inhibit" in CALLS.read_text())

    # 5) mode selection through the real D-Bus path
    cases = [((1696, 1200, 60), mid(1696, 1200, 60.000175)),
             ((1696, 1200, 90), mid(1696, 1200, 120.001221)),
             ((1920, 1080, 60), mid(1920, 1080, 60.0)),
             ((3840, 2160, 60), mid(3840, 2160, 60.0)),
             ((3840, 2160, 120), mid(2560, 1440, 120.0)),
             ((2316, 1080, 120), mid(2400, 1080, 120.001093))]
    for (w, h, f), want in cases:
        run("start", env=client(w, h, f))
        got = active().get(VIRT, ("-",))[0]
        check(f"client {w}x{h}@{f} -> {want}", got == want, got)
        run("stop")
    check("after several start/stop cycles only the physical monitor is on", active() == PHYS_ONLY, active())

    run("start", env=client(3840, 2160, 60, name="Living room TV"))
    check("4K TV: scale 2", active().get(VIRT, (0, 0))[1] == 2.0, active())
    run("stop")

    # 6) stale serial: retried
    edit(lambda s: s.update(fail_next_apply=1))
    run("start", env=client(1696, 1200, 60))
    check("retries after a stale-serial error", VIRT in active() and len(active()) == 1, active())
    run("stop")

    # 7) blanked displays are woken up
    edit(lambda s: s.update(power_save=3))
    run("start", env=client(1696, 1200, 60))
    check("wakes the displays (PowerSaveMode=0)", st()["power_save"] == 0)
    run("stop")

    # 8) the physical monitor disappears mid-stream
    run("start", env=client(1696, 1200, 60))
    saved = st()["monitors"][0]
    edit(lambda s: s.update(monitors=[m for m in s["monitors"] if m["connector"] != PHYS]))
    r = run("stop")
    check("stop without a physical monitor exits 0", r.returncode == 0)
    check("leaves the virtual display on when nothing else is connected", VIRT in active(), active())
    check("keeps the snapshot, marked inactive",
          state_file.exists() and not json.loads(state_file.read_text())["active"])
    # a new stream before the monitor is back must not overwrite the saved layout
    run("start", env=client(1920, 1080, 60))
    snap = json.loads(state_file.read_text())["snapshot"]
    check("a later start keeps the saved physical layout",
          [m[0] for lm in snap["logical"] for m in lm["monitors"]] == [PHYS], snap)
    edit(lambda s: s["monitors"].insert(0, saved))
    run("stop")
    check("once the monitor is back, stop restores it", active() == PHYS_ONLY, active())

    # 9) coexist mode
    write_config("DISABLE_PHYSICAL=false\n")
    run("start", env=client(1696, 1200, 120))
    a = active()
    check("coexist: physical + virtual to the right, virtual primary",
          a.get(PHYS, (0,))[0] == mid(2560, 1440, 165.0)
          and a.get(VIRT) == (mid(1696, 1200, 120.001221), 1.0, True, 2560, 0), a)
    run("stop")
    check("coexist: stop restores", active() == PHYS_ONLY, active())
    write_config()

    # 10) a scaled physical monitor comes back with its scale
    edit(lambda s: s["logical"][0].update(scale=2.0))
    run("start", env=client(1696, 1200, 60))
    run("stop")
    check("restores the physical monitor's scale 2",
          active() == {PHYS: (mid(2560, 1440, 165.0), 2.0, True, 0, 0)}, active())
    edit(lambda s: s["logical"][0].update(scale=1.0))

    # 11) misconfigured connector: start must not break the stream
    (cfg_dir / "config").write_text("CONNECTOR=DP-9\nSETTLE_SECONDS=0\n")
    r = run("start", env=client(1696, 1200, 60))
    check("unknown connector: start exits 0 and changes nothing",
          r.returncode == 0 and active() == PHYS_ONLY, r.stderr)
    write_config()

    # 12) no session bus at all
    r = run("start", env={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"})
    check("no D-Bus: start exits 0", r.returncode == 0, r.stderr)

    # 13) status / modes / connectors
    r = run("status")
    check("status works", r.returncode == 0 and VIRT in r.stdout, r.stdout + r.stderr)
    r = run("modes", "--test", "2316", "1080", "120")
    check("modes --test", "2400x1080@120.001" in r.stdout, r.stdout + r.stderr)
    r = run("connectors")
    check("connectors marks the forced connector", "virtual display (sunshine-vd)" in r.stdout, r.stdout)

    log = (HOME / ".local/state/sunshine-vd/sunshine-vd.log").read_text()
    check("log written", "start: client 'Tablet' requested 1696x1200@120" in log)
finally:
    mock.terminate()

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
