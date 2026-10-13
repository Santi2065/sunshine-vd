# sunshine-vd

**On-demand virtual display for [Sunshine](https://github.com/LizardByte/Sunshine) on GNOME (Wayland). No dummy plug, no kernel module.**

When a Moonlight or Artemis client connects, your monitor turns off and the desktop moves to a virtual display running at the client's own resolution and refresh rate. A tablet gets its native resolution, the TV at a friend's place gets 1080p60, and a Steam Deck gets 1280x800@90. When you quit the stream, everything goes back to how it was.

It does what [Apollo](https://github.com/ClassicOldSong/Apollo)'s virtual display does on Windows, but for GNOME on Linux, and on top of the Sunshine you already run.

_[Leer en castellano](README.es.md)_

<!-- TODO: add docs/demo.gif — a client connecting, the monitor turning off, and everything coming back on quit. -->

## Status

| | |
|---|---|
| **Tested** | Fedora 45 Workstation · GNOME on Wayland · NVIDIA RTX 3070 (proprietary driver 615) · Sunshine RPM |
| **Should work, untested** | AMD and Intel GPUs: the kernel side is generic DRM. Please file a [compatibility report](https://github.com/Santi2065/sunshine-vd/issues/new?template=compatibility_report.yml). |
| **Not supported yet** | KDE Plasma (use [Sunveil](https://github.com/ImStillBlue/sunshine-virtual-display)) · atomic Fedora (Silverblue, Bazzite) · the installer on non-Fedora distros (see the [manual steps](docs/how-it-works.md#manual-installation)) · Sunshine as a Flatpak (no KMS capture) |

## How it works

1. **Kernel.** A free DisplayPort/HDMI connector on your GPU is force-enabled with a custom EDID (`drm.edid_firmware=` + `video=<connector>:e`), so GNOME sees a monitor that is not there, offering your clients' resolutions. There is no kernel module involved, so Secure Boot is not a problem.
2. **Stream starts.** Sunshine's `global_prep_cmd` runs `sunshine-vd start`. Through GNOME's display API (`org.gnome.Mutter.DisplayConfig`), it makes the virtual display the only output, in the mode closest to what the client asked for.
3. **Stream ends.** `sunshine-vd stop` restores your layout.

The details, including why NVIDIA needs `:e` and how the EDID is built, are in [docs/how-it-works.md](docs/how-it-works.md).

## Requirements

- **Distro:** Fedora (non-atomic), which provides `grubby` and `dracut`.
- **Desktop:** GNOME on Wayland.
- **Sunshine:** installed natively (RPM) and capturing with KMS, which the RPM does by default.
- **Python bindings:** `python3-gobject`, installed by default on Fedora Workstation.
- **Hardware:** a free DisplayPort or HDMI connector on the GPU, with nothing plugged in.

## Install

```bash
git clone https://github.com/Santi2065/sunshine-vd
cd sunshine-vd
./install.sh --check   # shows the plan, changes nothing
./install.sh           # asks for your sudo password
# reboot
./install.sh --finish  # when GNOME asks whether to keep the display settings: Keep Changes
```

Between the reboot and `--finish`, GNOME treats the virtual display as a real monitor. If the login screen is not on your monitor, log in blind: press Enter, type your password and press Enter again.

The installer touches the following:
- **The EDID file**, written to `/usr/lib/firmware/edid/sunshine-vd.bin` and added to the initramfs.
- **Two kernel parameters**, added with `grubby` to every boot entry except the rescue one (which stays as an escape hatch). `grubby` also updates `GRUB_CMDLINE_LINUX` in `/etc/default/grub`. If your command line already has its own `video=` arguments, the installer stops, because `grubby` would replace them.
- **The helper and its settings:** `~/.local/bin/sunshine-vd` and `~/.config/sunshine-vd/` (settings, plus your display layout saved before the reboot so `--finish` can restore it exactly).
- **`sunshine.conf`:** it gets a `global_prep_cmd` entry plus `capture = kms` and `output_name = <connector>`. Your existing prep commands are kept, and the file is backed up first.
- **The GDM display layout** (only after confirmation), so the login screen does not show up on the virtual display.

`./uninstall.sh` reverts all of it. `output_name` and `capture` in `sunshine.conf` are only put back if they still hold the values the installer set.

## Usage

Connect from Moonlight or Artemis and choose the resolution and FPS in the client. To go back to your monitor, **quit** the app from the client. If you only disconnect, Sunshine keeps the session alive and the virtual display stays on.

| Command | What it does |
|---|---|
| `sunshine-vd status` | Shows which displays are on and in which mode |
| `sunshine-vd doctor` | Runs diagnostics: kernel parameters, EDID, GNOME, Sunshine config, duplicate Sunshine instances |
| `sunshine-vd stop` | Restores your monitors, for example if a stream ended badly. Super+P in GNOME also works. |
| `sunshine-vd connectors` | Lists the GPU's connectors and which one the installer would use |
| `sunshine-vd modes --test 2340 1080 120` | Shows which mode a client asking for that would get |

Steam Big Picture and games launched from it open on the virtual display, because it is the only display during the stream. Keep games in borderless fullscreen so they follow the client's resolution.

## Modes

The default EDID covers common clients. The first mode listed is the preferred one.

| Resolution | Hz | Typical client |
|---|---|---|
| 1920x1080 | 60, 120 | TVs, laptops |
| 2560x1440 | 60, 120 | monitors, 1440p TVs |
| 3840x2160 | 60 | 4K TVs (scale 2) |
| 1280x720 | 60 | slow connections |
| 2560x1600 | 60 | 16:10 tablets |
| 1280x800 | 60, 90 | Steam Deck (LCD / OLED) |
| 2400x1080 | 60, 120 | 20:9 phones |

If a client asks for something that is not in the list, the mode is picked in this order:
1. The closest aspect ratio.
2. Within that, a resolution that reaches the requested refresh rate. In games, fps matter more than pixels.
3. The smallest resolution that covers the request, because downscaling beats upscaling.

Sunshine scales whatever difference is left. A 4K120 request gets 2560x1440@120, and a 1366x768 TV gets 1080p.

To use your own modes, reinstall with `MODES` and reboot:

```bash
# 17:12 tablet at half resolution (e.g. OnePlus Pad 3)
MODES="1696x1200@60,1696x1200@120,1696x1200@144,3392x2400@60,1920x1080@60,1920x1080@120,3840x2160@60,1280x720@60" ./install.sh
# iPad Pro 11"
MODES="2388x1668@60,2388x1668@120,1194x834@120,1920x1080@60,1920x1080@120,3840x2160@60" ./install.sh
```

**Limits:**
- Up to 8 modes with their own timing, plus the standard TV modes for free (1920x1080@60/120, 3840x2160@60 and 1280x720@60).
- A pixel clock of at most 655 MHz per mode, which rules out 4K@120.
- Preview the result with `./sunshine-vd make-edid --modes "..." --out /tmp/test.bin`.

## Configuration

`~/.config/sunshine-vd/config` takes effect on the next stream:

| Key | Default | Meaning |
|---|---|---|
| `CONNECTOR` | set by the installer | Connector the virtual display lives on |
| `DISABLE_PHYSICAL` | `true` | `false` adds the virtual display to the right of your monitors instead of replacing them |
| `SCALE` | `auto` | `auto` uses 1 below 2000 px of height and 2 from there up; or a fixed value like `1.5` |
| `WAKE_DISPLAYS` | `true` | Wakes blanked displays before switching |
| `INHIBIT_IDLE` | `true` | Keeps GNOME from blanking or locking during the stream |
| `SETTLE_SECONDS` | `1.5` | Pause after the switch, before Sunshine starts capturing |
| `SUNSHINE_CONF` | empty | Path to `sunshine.conf`, if it is not the default one |

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md). The two most important cases:

- **No picture after the reboot:** boot the "rescue" entry from the GRUB menu, or press `e` on the normal entry, delete `drm.edid_firmware=…` and `video=…:e` from the `linux` line, and boot with Ctrl+X. Then run `./uninstall.sh`. Older kernel entries do not help, because they have the parameters too.
- **No picture on your monitor after streaming:** run `sunshine-vd stop` (over SSH if needed) or press Super+P.

## Limitations

- **No HDR or VRR on the virtual display with NVIDIA.** The driver only exposes them on real HDMI 2.1 links, so streams to HDR TVs are SDR.
- **New EDID modes need a reboot.** NVIDIA reads the EDID once, at boot.
- **Keep the virtual display's connector empty.** Do not plug a monitor into it while sunshine-vd is installed.

## Credits

- The forced-connector + custom-EDID approach, and the detail that NVIDIA needs `video=<connector>:e`, come from [EnriqueWood's proof of concept](https://github.com/EnriqueWood/sunshine-virtual-displays-support-poc).
- [Sunveil](https://github.com/ImStillBlue/sunshine-virtual-display) does the same job on KDE Plasma.
- [Apollo](https://github.com/ClassicOldSong/Apollo) set the bar with per-client virtual displays on Windows.

sunshine-vd is an independent project, not affiliated with LizardByte, Sunshine or Moonlight.

## License

[MIT](LICENSE)
