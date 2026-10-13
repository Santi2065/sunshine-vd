# Changelog

## 0.1.0 — 2026-10-13

First public release.

- Virtual display through a force-enabled connector with a generated EDID
  (default modes for TVs, 16:10 tablets, the Steam Deck and 20:9 phones;
  custom modes with `MODES=…`).
- Per-client mode selection on stream start through GNOME's
  `org.gnome.Mutter.DisplayConfig` API, with the previous layout restored on
  stop. Optional "coexist" mode keeps the physical monitors on.
- Installer for Fedora (`grubby` + `dracut`) with `--check` and `--finish`:
  keeps existing Sunshine prep commands (multi-line lists and comments
  included), leaves the rescue boot entry clean, refuses to clobber existing
  `video=` arguments or connectors shared between GPUs, and restores the
  display layout saved before the reboot. Uninstaller that reverts everything,
  starting with the kernel parameters.
- `sunshine-vd doctor`, `status`, `connectors` and `modes --test`.
- Tests: EDID validation, mode selection, `sunshine.conf` editing, the helper
  against a fake Mutter over D-Bus, and an installer simulation; run in CI.
