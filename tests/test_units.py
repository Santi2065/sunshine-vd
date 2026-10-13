#!/usr/bin/env python3
"""Unit tests: EDID generation, mode selection, sunshine.conf editing and
connector discovery. No D-Bus or root needed.

    python3 tests/test_units.py
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "sunshine-vd"

_loader = importlib.machinery.SourceFileLoader("sunshine_vd", str(HELPER))
_spec = importlib.util.spec_from_loader("sunshine_vd", _loader)
svd = importlib.util.module_from_spec(_spec)
_loader.exec_module(svd)


def run_helper(*args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(HELPER), *args], env=e,
                          capture_output=True, text=True, timeout=30)


def decode_dtd(d):
    return {
        "w": d[2] | (d[4] >> 4) << 8,
        "h": d[5] | (d[7] >> 4) << 8,
        "clock_10khz": d[0] | d[1] << 8,
    }


def edid_contents(edid):
    """(list of DTD (w, h), list of VICs) found in the base block + CTA extension."""
    dtds = []
    for i in range(4):
        d = edid[54 + 18 * i: 72 + 18 * i]
        if d[0] or d[1]:
            dd = decode_dtd(d)
            dtds.append((dd["w"], dd["h"]))
    ext = edid[128:]
    vics, off = [], 4
    while off < ext[2]:
        tag, length = ext[off] >> 5, ext[off] & 0x1F
        if tag == 2:
            vics += list(ext[off + 1: off + 1 + length])
        off += 1 + length
    off = ext[2]
    while off + 18 <= 127 and (ext[off] or ext[off + 1]):
        dd = decode_dtd(ext[off: off + 18])
        dtds.append((dd["w"], dd["h"]))
        off += 18
    return dtds, vics


class TestEdid(unittest.TestCase):
    def build(self, spec):
        return svd.build_edid(svd.parse_modes(spec))[0]

    def assert_valid(self, edid):
        self.assertEqual(len(edid), 256)
        self.assertEqual(edid[:8], b"\x00\xff\xff\xff\xff\xff\xff\x00")
        self.assertEqual(sum(edid[:128]) % 256, 0, "base block checksum")
        self.assertEqual(sum(edid[128:]) % 256, 0, "extension checksum")
        self.assertEqual((edid[18], edid[19]), (1, 4), "EDID 1.4")
        self.assertEqual(edid[126], 1, "one extension block")
        self.assertEqual(edid[128], 0x02, "CTA-861 extension")

    def edid_decode_ok(self, edid):
        if not shutil.which("edid-decode"):
            self.skipTest("edid-decode not installed")
        with tempfile.NamedTemporaryFile(suffix=".bin") as f:
            f.write(edid)
            f.flush()
            r = subprocess.run(["edid-decode", "--check", f.name], capture_output=True, text=True)
        out = r.stdout + r.stderr
        self.assertIn("EDID conformity: PASS", out, out)
        self.assertNotIn("Warnings:", out, out)

    def test_default_modes(self):
        edid = self.build(svd.DEFAULT_MODES)
        self.assert_valid(edid)
        dtds, vics = edid_contents(edid)
        self.assertEqual(dtds[0], (1920, 1080), "preferred mode first")
        self.assertEqual(sorted(vics), sorted([63, 97, 4]))
        self.assertEqual(len(dtds), 8)
        self.edid_decode_ok(edid)

    def test_tablet_modes(self):
        spec = ("1696x1200@60,1696x1200@120,1696x1200@144,3392x2400@60,2560x1440@60,"
                "2560x1440@120,2400x1080@60,2400x1080@120,1920x1080@60,1920x1080@120,"
                "3840x2160@60,1280x720@60")
        edid = self.build(spec)
        self.assert_valid(edid)
        self.assertEqual(edid_contents(edid)[0][0], (1696, 1200))
        self.edid_decode_ok(edid)

    def test_single_mode(self):
        edid = self.build("1280x800@90")
        self.assert_valid(edid)
        self.assertEqual(edid_contents(edid)[0], [(1280, 800)])
        self.edid_decode_ok(edid)

    def test_standard_mode_first_becomes_dtd(self):
        edid = self.build("1920x1080@60,1920x1080@120")
        dtds, vics = edid_contents(edid)
        self.assertEqual(dtds, [(1920, 1080)])
        self.assertEqual(vics, [63])

    def test_refresh_accuracy(self):
        for (w, h, r) in [(1920, 1080, 60), (1696, 1200, 144), (2560, 1440, 120), (1280, 800, 90)]:
            t = svd.cvt_rb_timing(w, h, r)
            self.assertAlmostEqual(t["refresh_real"], r, delta=0.01, msg=f"{w}x{h}@{r}")

    def test_errors(self):
        with self.assertRaisesRegex(ValueError, "pixel clock"):
            self.build("3840x2160@144")
        with self.assertRaisesRegex(ValueError, "too many modes"):
            self.build(",".join(f"{w}x1000@60" for w in range(1300, 2300, 100)))
        with self.assertRaisesRegex(ValueError, "invalid mode"):
            svd.parse_modes("1920x1080")
        with self.assertRaisesRegex(ValueError, "out of range"):
            svd.parse_modes("1920x1080@500")
        self.assertEqual(svd.parse_modes("1920x1080@60, 1920x1080@60"), [(1920, 1080, 60.0)])

    def test_cli_error_exit_code(self):
        r = run_helper("make-edid", "--modes", "3840x2160@144", "--out", os.devnull)
        self.assertEqual(r.returncode, 2)
        self.assertIn("pixel clock", r.stderr)


def gnome_modes(spec):
    """What GNOME would list for an EDID built from spec (plus the mandatory 640x480)."""
    out = []
    for (w, h, r) in svd.parse_modes(spec) + [(640, 480, 59.94)]:
        out.append({"id": f"{w}x{h}@{r:.3f}", "width": w, "height": h, "refresh": float(r)})
    return out


class TestChooseMode(unittest.TestCase):
    def pick(self, modes, w, h, fps):
        m = svd.choose_mode(modes, w, h, fps)
        return (m["width"], m["height"], round(m["refresh"]))

    def test_default_modes(self):
        modes = gnome_modes(svd.DEFAULT_MODES)
        cases = {
            (1920, 1080, 60): (1920, 1080, 60),
            (1920, 1080, 120): (1920, 1080, 120),
            (3840, 2160, 60): (3840, 2160, 60),
            (3840, 2160, 120): (2560, 1440, 120),   # fps first
            (1366, 768, 60): (1920, 1080, 60),      # downscale beats upscale
            (1280, 800, 90): (1280, 800, 90),       # Steam Deck OLED
            (1280, 800, 60): (1280, 800, 60),
            (1920, 1200, 60): (2560, 1600, 60),     # closest 16:10 that covers it
            (2340, 1080, 120): (2400, 1080, 120),   # 19.5:9 phone
            (5120, 2880, 60): (3840, 2160, 60),     # larger than anything: the largest
            (800, 600, 30): (1280, 800, 60),        # 4:3 -> closest is 16:10; never 640x480
        }
        for (w, h, f), want in cases.items():
            with self.subTest(client=f"{w}x{h}@{f}"):
                self.assertEqual(self.pick(modes, w, h, f), want)

    def test_tablet_modes(self):
        modes = gnome_modes("1696x1200@60,1696x1200@120,1696x1200@144,3392x2400@60,"
                            "1920x1080@60,1920x1080@120")
        self.assertEqual(self.pick(modes, 1696, 1200, 90), (1696, 1200, 120))
        self.assertEqual(self.pick(modes, 1696, 1200, 165), (1696, 1200, 144))
        self.assertEqual(self.pick(modes, 3392, 2400, 60), (3392, 2400, 60))
        self.assertEqual(self.pick(modes, 3392, 2400, 120), (1696, 1200, 120))
        self.assertEqual(self.pick(modes, 1700, 1200, 120), (1696, 1200, 120))

    def test_small_custom_mode(self):
        modes = gnome_modes("2388x1668@60,2388x1668@120,1194x834@120,1920x1080@60")
        self.assertEqual(self.pick(modes, 1194, 834, 120), (1194, 834, 120))
        self.assertEqual(self.pick(modes, 2388, 1668, 120), (2388, 1668, 120))

    def test_scale(self):
        self.assertEqual(svd.choose_scale({"height": 2160, "scales": [1.0, 2.0, 3.0]}, "auto"), 2.0)
        self.assertEqual(svd.choose_scale({"height": 1080, "scales": [1.0, 2.0]}, "auto"), 1.0)
        self.assertEqual(svd.choose_scale({"height": 1080, "scales": [1.0, 1.5, 2.0]}, "1.5"), 1.5)
        self.assertEqual(svd.choose_scale({"height": 1080, "scales": [1.0, 2.0]}, "1.25"), 1.0)


class TestUnitFromCgroup(unittest.TestCase):
    def test_service(self):
        cg = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-dev.lizardbyte.app.Sunshine.service\n"
        self.assertEqual(svd.unit_from_cgroup(cg), "app-dev.lizardbyte.app.Sunshine.service")

    def test_terminal_scope_is_not_user_manager(self):
        cg = ("0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
              "app-org.gnome.Ptyxis.slice/vte-spawn-1234.scope\n")
        self.assertEqual(svd.unit_from_cgroup(cg), "")

    def test_shell_agrees(self):
        script = (ROOT / "install.sh").read_text()
        func = script[script.index("unit_from_cgroup() {"):script.index("# Sunshine processes of this user")]
        with tempfile.TemporaryDirectory() as d:
            for name, text, want in (
                ("svc", "0::/user.slice/user@1000.service/app.slice/my-sunshine.service\n", "my-sunshine.service"),
                ("scope", "0::/user.slice/user@1000.service/app.slice/vte-spawn-1.scope\n", "(no-unit)"),
                ("mgr", "0::/user.slice/user-1000.slice/user@1000.service\n", "(no-unit)"),
            ):
                f = Path(d) / name
                f.write_text(text)
                r = subprocess.run(["bash", "-c", func + f'\nunit_from_cgroup "{f}"'],
                                   capture_output=True, text=True)
                self.assertEqual(r.stdout.strip(), want, name)


class TestSunshineConf(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.conf = self.dir / "sunshine.conf"

    def tearDown(self):
        shutil.rmtree(self.dir)

    def helper(self, *args):
        r = run_helper(*args, "--file", str(self.conf))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_round_trip_keeps_user_commands(self):
        mine = [{"do": "/usr/local/bin/wake on", "undo": "/usr/local/bin/wake off"}]
        original = (f"origin_web_ui_allowed = pc\noutput_name = 0\n"
                    f"global_prep_cmd = {json.dumps(mine)}\n")
        self.conf.write_text(original)
        self.helper("sunshine-conf", "add", "--bin", "/x/sunshine-vd", "--connector", "DP-3")
        self.helper("sunshine-conf", "add", "--bin", "/x/sunshine-vd", "--connector", "DP-3")
        text = self.conf.read_text()
        cmds = json.loads(svd.conf_get(text.splitlines(), "global_prep_cmd"))
        self.assertEqual(cmds, mine + [{"do": "/x/sunshine-vd start", "undo": "/x/sunshine-vd stop"}])
        self.assertIn("capture = kms", text)
        self.assertIn("output_name = DP-3", text)
        self.helper("sunshine-conf", "remove", "--restore-output", "0", "--restore-capture", "")
        text = self.conf.read_text()
        self.assertEqual(json.loads(svd.conf_get(text.splitlines(), "global_prep_cmd")), mine)
        self.assertNotIn("capture", text)
        self.assertIn("output_name = 0", text)
        self.assertIn("origin_web_ui_allowed = pc", text)

    def test_from_scratch(self):
        self.helper("sunshine-conf", "add", "--bin", "/x/sunshine-vd", "--connector", "DP-2")
        self.helper("sunshine-conf", "remove", "--restore-output", "", "--restore-capture", "")
        self.assertEqual(self.conf.read_text().strip(), "")

    def test_multiline_list_and_comments(self):
        self.conf.write_text(
            "# mine\n"
            "origin_web_ui_allowed = pc   # only here\n"
            "global_prep_cmd = [\n"
            '  {"do": "/home/u/sunshine-vd-hooks/hdr.sh on", "undo": "/home/u/sunshine-vd-hooks/hdr.sh off"},  # hdr\n'
            '  {"do": "/usr/local/bin/wake on", "undo": "/usr/local/bin/wake off"}\n'
            "]\n"
            "output_name = 1 # main\n"
            "capture = nvfbc\n")
        self.helper("sunshine-conf", "check")
        self.helper("sunshine-conf", "add", "--bin", "/x/sunshine-vd", "--connector", "DP-3")
        lines = self.conf.read_text().splitlines()
        cmds = json.loads(svd.conf_get(lines, "global_prep_cmd"))
        self.assertEqual(len(cmds), 3, "user hooks whose path contains 'sunshine-vd' are kept")
        self.assertEqual(svd.conf_get(lines, "origin_web_ui_allowed"), "pc")
        self.assertEqual(sum(1 for ln in lines if ln.startswith("global_prep_cmd")), 1)
        self.assertFalse(any(ln.strip() == "]" for ln in lines), "the old multi-line value is gone")
        self.helper("sunshine-conf", "remove", "--restore-output", "1", "--expect-output", "DP-3",
                    "--restore-capture", "nvfbc")
        lines = self.conf.read_text().splitlines()
        self.assertEqual(len(json.loads(svd.conf_get(lines, "global_prep_cmd"))), 2)
        self.assertEqual(svd.conf_get(lines, "output_name"), "1")
        self.assertEqual(svd.conf_get(lines, "capture"), "nvfbc")

    def test_remove_without_recorded_values_keeps_them(self):
        self.conf.write_text("output_name = 1\ncapture = nvfbc\n")
        self.helper("sunshine-conf", "remove")
        self.assertEqual(self.conf.read_text(), "output_name = 1\ncapture = nvfbc\n")

    def test_remove_does_not_touch_values_the_user_changed(self):
        self.conf.write_text("output_name = HDMI-A-1\ncapture = wlr\n")
        self.helper("sunshine-conf", "remove", "--restore-output", "0", "--expect-output", "DP-3",
                    "--restore-capture", "")
        self.assertEqual(self.conf.read_text(), "output_name = HDMI-A-1\ncapture = wlr\n")

    def test_rejects_garbage(self):
        self.conf.write_text("global_prep_cmd = not json\n")
        r = run_helper("sunshine-conf", "add", "--file", str(self.conf))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(run_helper("sunshine-conf", "check", "--file", str(self.conf)).returncode, 1)
        self.assertEqual(self.conf.read_text(), "global_prep_cmd = not json\n")


class TestConnectors(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.sys = self.dir / "drm"
        (self.sys / "card1" / "device").mkdir(parents=True)
        (self.sys / "card1" / "device" / "vendor").write_text("0x10de\n")
        for name, status in (("DP-1", "connected"), ("DP-2", "disconnected"), ("DP-3", "disconnected"),
                             ("HDMI-A-1", "disconnected"), ("Writeback-1", "unknown")):
            d = self.sys / f"card1-{name}"
            d.mkdir()
            (d / "status").write_text(status + "\n")
            (d / "enabled").write_text("disabled\n")
        self.cmdline = self.dir / "cmdline"
        self.cmdline.write_text("ro rhgb quiet\n")
        self.env = {"VD_SYSFS_DRM": str(self.sys), "VD_PROC_CMDLINE": str(self.cmdline)}

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_pick_and_validate(self):
        r = run_helper("connectors", "--pick", env=self.env)
        self.assertEqual(r.stdout.strip(), "DP-3")
        self.assertEqual(run_helper("connectors", "--validate", "DP-2", env=self.env).returncode, 0)
        self.assertEqual(run_helper("connectors", "--validate", "DP-1", env=self.env).returncode, 3)
        self.assertEqual(run_helper("connectors", "--validate", "DP-7", env=self.env).returncode, 2)
        r = run_helper("connectors", env=self.env)
        self.assertIn("installer would use", r.stdout)
        self.assertNotIn("Writeback", r.stdout)
        self.assertIn("NVIDIA", r.stdout)

    def test_forced_connector_wins(self):
        self.cmdline.write_text("ro drm.edid_firmware=DP-2:edid/sunshine-vd.bin video=DP-2:e\n")
        (self.sys / "card1-DP-2" / "status").write_text("connected\n")
        self.assertEqual(run_helper("connectors", "--pick", env=self.env).stdout.strip(), "DP-2")
        self.assertEqual(run_helper("connectors", "--validate", "DP-2", env=self.env).returncode, 0)

    def test_same_name_on_two_gpus(self):
        (self.sys / "card0" / "device").mkdir(parents=True)
        (self.sys / "card0" / "device" / "vendor").write_text("0x8086\n")
        for name, status in (("DP-3", "connected"), ("DP-2", "disconnected")):
            d = self.sys / f"card0-{name}"
            d.mkdir()
            (d / "status").write_text(status + "\n")
        # DP-3 is free on the NVIDIA card but connected on the Intel one; DP-2 exists on both.
        self.assertEqual(run_helper("connectors", "--validate", "DP-3", env=self.env).returncode, 4)
        self.assertEqual(run_helper("connectors", "--validate", "DP-2", env=self.env).returncode, 4)
        self.assertEqual(run_helper("connectors", "--pick", env=self.env).stdout.strip(), "HDMI-A-1")

    def test_hdmi_fallback(self):
        for n in ("DP-2", "DP-3"):
            (self.sys / f"card1-{n}" / "status").write_text("connected\n")
        self.assertEqual(run_helper("connectors", "--pick", env=self.env).stdout.strip(), "HDMI-A-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
