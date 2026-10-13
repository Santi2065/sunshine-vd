#!/usr/bin/env python3
"""A fake org.gnome.Mutter.DisplayConfig D-Bus service for tests.

It implements the two methods sunshine-vd uses (GetCurrentState and
ApplyMonitorsConfig, with the same signatures as Mutter) plus the
PowerSaveMode property. Its state lives in a JSON file (MOCK_STATE) that the
tests read and modify. ApplyMonitorsConfig validates like Mutter does: the
serial, connectors, mode ids, scales, exactly one primary, and logical
monitors that touch without overlapping.

Prints READY once it owns the bus name.
"""
import json
import os
import sys

import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

STATE = os.environ["MOCK_STATE"]

XML = """
<node>
 <interface name="org.gnome.Mutter.DisplayConfig">
  <method name="GetCurrentState">
   <arg name="serial" direction="out" type="u"/>
   <arg name="monitors" direction="out" type="a((ssss)a(siiddada{sv})a{sv})"/>
   <arg name="logical_monitors" direction="out" type="a(iiduba(ssss)a{sv})"/>
   <arg name="properties" direction="out" type="a{sv}"/>
  </method>
  <method name="ApplyMonitorsConfig">
   <arg name="serial" direction="in" type="u"/>
   <arg name="method" direction="in" type="u"/>
   <arg name="logical_monitors" direction="in" type="a(iiduba(ssa{sv}))"/>
   <arg name="properties" direction="in" type="a{sv}"/>
  </method>
  <property name="PowerSaveMode" type="i" access="readwrite"/>
 </interface>
</node>
"""


class ConfigError(Exception):
    pass


def load():
    with open(STATE) as f:
        return json.load(f)


def save(st):
    with open(STATE, "w") as f:
        json.dump(st, f, indent=1)


def mode_by_id(mon, mid):
    return next((m for m in mon["modes"] if m["id"] == mid), None)


def get_current_state(st):
    mons = []
    for mon in st["monitors"]:
        modes = []
        for m in mon["modes"]:
            p = {}
            if m["id"] == mon.get("current"):
                p["is-current"] = GLib.Variant("b", True)
            if m.get("preferred"):
                p["is-preferred"] = GLib.Variant("b", True)
            modes.append((m["id"], m["w"], m["h"], m["r"], 1.0, m.get("scales", [1.0, 2.0]), p))
        props = {"display-name": GLib.Variant("s", mon["name"])}
        mons.append(((mon["connector"], mon["vendor"], mon["product"], mon["serial"]), modes, props))
    lms = []
    for lm in st["logical"]:
        specs = []
        for c in lm["connectors"]:
            mon = next(m for m in st["monitors"] if m["connector"] == c)
            specs.append((c, mon["vendor"], mon["product"], mon["serial"]))
        lms.append((lm["x"], lm["y"], lm["scale"], lm["transform"], lm["primary"], specs, {}))
    props = {"layout-mode": GLib.Variant("u", st["layout_mode"]),
             "supports-changing-layout-mode": GLib.Variant("b", True)}
    return GLib.Variant("(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})",
                        (st["serial"], mons, lms, props))


def rects_touch(a, b):
    horiz = (a[0] + a[2] == b[0] or b[0] + b[2] == a[0]) and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
    vert = (a[1] + a[3] == b[1] or b[1] + b[3] == a[1]) and a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
    return horiz or vert


def apply(st, serial, method, lms, props):
    if st.get("fail_next_apply"):
        st["fail_next_apply"] -= 1
        st["serial"] += 1
        raise ConfigError("The requested configuration is based on stale information")
    if serial != st["serial"]:
        raise ConfigError("The requested configuration is based on stale information")
    layout = props.get("layout-mode", st["layout_mode"])
    if not lms:
        raise ConfigError("Monitor configuration is empty")
    if sum(1 for lm in lms if lm[4]) != 1:
        raise ConfigError("Config needs exactly one primary logical monitor")
    rects, new_current, used = [], {}, set()
    for (x, y, scale, _transform, _primary, monitors) in lms:
        if not monitors:
            raise ConfigError("Logical monitor has no monitors")
        for (c, mid, _mp) in monitors:
            mon = next((m for m in st["monitors"] if m["connector"] == c), None)
            if not mon:
                raise ConfigError(f"Invalid connector '{c}' specified")
            md = mode_by_id(mon, mid)
            if not md:
                raise ConfigError(f"Invalid mode '{mid}' specified")
            if c in used:
                raise ConfigError("Monitor used twice")
            used.add(c)
            if scale not in md.get("scales", [1.0, 2.0]):
                raise ConfigError(f"Scale {scale} not valid for resolution {md['w']}x{md['h']}")
            new_current[c] = mid
            if layout == 2:
                w, h = md["w"], md["h"]
            else:
                w, h = round(md["w"] / scale), round(md["h"] / scale)
        rects.append((x, y, w, h))
    for i, a in enumerate(rects):
        for j, b in enumerate(rects):
            if i < j and a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                raise ConfigError("Logical monitors overlap")
    if len(rects) > 1:
        for i, a in enumerate(rects):
            if not any(rects_touch(a, b) for j, b in enumerate(rects) if i != j):
                raise ConfigError("Logical monitors not adjacent")
    if min(r[0] for r in rects) != 0 or min(r[1] for r in rects) != 0:
        raise ConfigError("Logical monitors positions are offset")
    if method == 0:
        return
    st["logical"] = [{"x": x, "y": y, "scale": scale, "transform": t, "primary": p,
                      "connectors": [m[0] for m in mons]} for (x, y, scale, t, p, mons) in lms]
    for mon in st["monitors"]:
        mon["current"] = new_current.get(mon["connector"])
    st["layout_mode"] = layout
    st["serial"] += 1
    st.setdefault("applied", []).append({"method": method, "logical": st["logical"]})


def on_call(conn, sender, path, iface, method, params, inv):
    st = load()
    try:
        if method == "GetCurrentState":
            inv.return_value(get_current_state(st))
        elif method == "ApplyMonitorsConfig":
            serial, m, lms, props = params.unpack()
            apply(st, serial, m, lms, props)
            inv.return_value(None)
        save(st)
    except ConfigError as e:
        save(st)
        inv.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", str(e))
    except Exception as e:  # noqa: BLE001
        inv.return_dbus_error("org.freedesktop.DBus.Error.Failed", f"mock crash: {e!r}")


def on_get(conn, sender, path, iface, prop):
    return GLib.Variant("i", load().get("power_save", 0))


def on_set(conn, sender, path, iface, prop, value):
    st = load()
    st["power_save"] = value.unpack()
    save(st)
    return True


def on_bus(conn, name):
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object("/org/gnome/Mutter/DisplayConfig", node.interfaces[0], on_call, on_get, on_set)


Gio.bus_own_name(Gio.BusType.SESSION, "org.gnome.Mutter.DisplayConfig",
                 Gio.BusNameOwnerFlags.NONE, on_bus, lambda *a: print("READY", flush=True),
                 lambda *a: sys.exit(1))
GLib.MainLoop().run()
