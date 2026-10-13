# Troubleshooting

Start with `sunshine-vd doctor`. It checks the kernel parameters, the EDID, what GNOME sees, Sunshine's config, and whether more than one Sunshine is running.

**Logs:**
- `~/.local/state/sunshine-vd/sunshine-vd.log` has what the helper did on each stream start and stop.
- `~/.config/sunshine/sunshine.log` is Sunshine's own log.

## No picture after rebooting

This is very unlikely, but it is the scary one, so here is the way out. The virtual display only exists because of two kernel parameters, so boot once without them. Either:

- **Boot the rescue entry.** Pick the "rescue" entry in the GRUB menu. The installer leaves it untouched.
- **Edit the boot entry:**
  1. In the GRUB menu, select the entry and press `e`. If the menu is hidden, hold Shift or press Esc during boot.
  2. On the line starting with `linux`, delete `drm.edid_firmware=…:edid/sunshine-vd.bin` and `video=…:e`.
  3. Press Ctrl+X to boot.

Then run `./uninstall.sh` and reboot. Older kernel entries do not help: they have the parameters too.

## The login screen appears on a display I cannot see

GDM has its own display layout. Until it is fixed you can still log in blind: press Enter, type your password and press Enter again. Then either run `./install.sh --finish` again and accept copying your layout to GDM (running it several times is safe), or copy it by hand:

```bash
sudo install -o gdm -g gdm -m 644 ~/.config/monitors.xml /var/lib/gdm/.config/monitors.xml
```

## My monitor stays black after a stream

The stream probably did not end with Quit; Sunshine keeps a session alive after a plain disconnect. Run `sunshine-vd stop`, from an SSH session if needed, or press Super+P to cycle layouts. Next time, quit the app from the client.

## `sunshine-vd doctor`: "the kernel sees DP-x as 'disconnected'"

The EDID did not load on that connector. Check:

```bash
cat /proc/cmdline                    # are both parameters there?
sudo dmesg | grep -i edid            # did the kernel find the file?
sudo lsinitrd | grep sunshine-vd     # is the EDID in the initramfs?
sunshine-vd connectors
```

Some NVIDIA cards list more DP connectors than physical ports. Try another one:

```bash
./uninstall.sh                       # reboot
VD_CONNECTOR=DP-2 ./install.sh       # reboot, then ./install.sh --finish
```

## Sunshine restarts in a loop / "Address already in use"

Two Sunshine instances are running, for example the official `app-dev.lizardbyte.app.Sunshine.service` plus a unit you wrote yourself. Only one can own the ports, and the other one keeps failing. `sunshine-vd doctor` lists both. Keep one:

```bash
systemctl --user disable --now my-sunshine.service
systemctl --user reset-failed app-dev.lizardbyte.app.Sunshine.service
systemctl --user restart app-dev.lizardbyte.app.Sunshine.service
```

## The stream shows my real monitor, not the virtual display

- **Check the config.** `capture = kms` and `output_name = <connector>` must be in `sunshine.conf`.
- **Check the helper's log.** `sunshine-vd.log` should show `virtual display DP-x set to …` for that stream. If instead it says GNOME does not see the connector, see the section above about the EDID not loading.
- **Check the Sunshine package.** Sunshine has to be the native package. The Flatpak cannot use KMS capture.

## `install.sh` says my command line already has `video=…`

`grubby --args=video=…` replaces every existing `video=` argument, so the installer refuses instead of silently dropping yours (for example `video=efifb:off` for GPU passthrough). Follow the [manual installation](how-it-works.md#manual-installation) and keep both: `video=efifb:off video=DP-3:e`.

## `install.sh` says GNOME remembers a monitor on that connector

A DisplayPort monitor that is switched off can look "disconnected", and forcing that port would hijack it. If the port really is empty (for example, you unplugged a monitor for good), run `VD_CONNECTOR=DP-3 ./install.sh`; otherwise pick another one from `sunshine-vd connectors`.

## The client gets an unexpected resolution

Check which mode a client asking for that resolution would get:

```bash
sunshine-vd modes --test 2340 1080 120
```

If the mode you want is missing, add it with `MODES=… ./install.sh` and reboot. See [Modes](../README.md#modes).

## A game renders at the wrong resolution

On Wayland, games cannot change the real display mode. Use borderless or "fullscreen window" mode. If a game saved the resolution of your physical monitor, change it once in its settings.

## No HDR on my HDR TV

This is expected. NVIDIA does not expose HDR on forced or virtual connectors, so the stream is SDR.
