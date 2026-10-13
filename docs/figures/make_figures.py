"""Regenerates the diagram shown in the README.

    pip install matplotlib
    python docs/figures/make_figures.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
for f in Path("/usr/share/fonts/lm").glob("lm*10-*.otf"):  # Latin Modern, if installed
    font_manager.fontManager.addfont(str(f))
plt.style.use(HERE / "paper.mplstyle")
C = plt.rcParams["axes.prop_cycle"].by_key()["color"]
INK, GRAY = "#1a1a1a", "#8c8c8c"


def tint(hex_color, a):
    """Mixes a palette color with white (a = share of the color)."""
    rgb = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(255 - a * (255 - c)):02x}" for c in rgb)


def box(ax, x, y, w, h, title, body, color, dashed=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2",
                                fc=tint(color, 0.10), ec=color, lw=1.0, ls="--" if dashed else "-"))
    ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="center", fontsize=9.5, weight="bold", color=color)
    ax.text(x + w / 2, y + (h - 4.2) / 2, body, ha="center", va="center", fontsize=7.6, color=INK, linespacing=1.35)


def arrow(ax, p, q, label=None, color=INK, lpos=0.5, dx=0.0, dy=0.0, ha="center", rad=0.0, ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=9, lw=0.9, color=color,
                                 shrinkA=1, shrinkB=1, linestyle=ls, connectionstyle=f"arc3,rad={rad}"))
    if label:
        x, y = p[0] + (q[0] - p[0]) * lpos + dx, p[1] + (q[1] - p[1]) * lpos + dy
        ax.text(x, y, label, ha=ha, va="center", fontsize=7.4, color=color, style="italic")


def step(ax, x, y, n, color):
    ax.add_patch(plt.Circle((x, y), 1.55, fc="white", ec=color, lw=0.9, zorder=5))
    ax.text(x, y - 0.05, str(n), ha="center", va="center", fontsize=7.6, weight="bold", color=color, zorder=6)


fig, ax = plt.subplots(figsize=(7.4, 3.85))
ax.set_xlim(0, 116)
ax.set_ylim(0, 60)
ax.set_aspect("equal")
ax.axis("off")

# host machine frame
ax.add_patch(FancyBboxPatch((24, 1), 90, 57, boxstyle="round,pad=0,rounding_size=1.5",
                            fc="#f7f7f7", ec="#bdbdbd", lw=0.8, ls="--"))
ax.text(26, 55.6, "Host: Fedora · GNOME on Wayland", ha="left", va="center", fontsize=7.8, color=GRAY, style="italic")

# client
box(ax, 1, 38.5, 19, 15, "Client", "Moonlight or\nArtemis, asks for\n2560×1600 @ 60", C[3])

# host stack
X, W = 28, 46
cx = X + W / 2
box(ax, X, 42, W, 11, "Sunshine", "global_prep_cmd runs sunshine-vd\nKMS capture of output_name = DP-3", C[0])
box(ax, X, 28.5, W, 10.5, "sunshine-vd", "start: save the layout, pick the closest mode\nstop: restore the saved layout", C[1])
box(ax, X, 15.5, W, 10, "GNOME (Mutter)", "org.gnome.Mutter.DisplayConfig\nApplyMonitorsConfig, temporary", C[2])
box(ax, X, 3, W, 9.5, "Kernel (DRM)", "drm.edid_firmware=DP-3:edid/sunshine-vd.bin\nvideo=DP-3:e   (set once, at boot)", C[5])

# displays during the stream
ax.text(96.5, 52.3, "Displays during a stream", ha="center", va="center", fontsize=7.8, color=GRAY, style="italic")
box(ax, 82, 36, 29, 13, "Virtual display", "DP-3, nothing plugged in\non at 2560×1600 @ 60", C[0], dashed=True)
box(ax, 82, 15, 29, 10.5, "Your monitor", "off until the stream ends", GRAY)

# 1 launch / video stream
arrow(ax, (20, 49), (X, 49), color=C[3])
ax.text(24, 51.2, "1 launch", ha="center", va="center", fontsize=7.2, color=C[3], style="italic")
arrow(ax, (X, 45), (20, 45), color=C[0])
ax.text(24, 42.8, "stream", ha="center", va="center", fontsize=7.2, color=C[0], style="italic")
# 2-4 down the stack
for (y0, y1), n, lab in (((42, 39), 2, "start"), ((28.5, 25.5), 3, "apply layout"), ((15.5, 12.5), 4, "modeset")):
    arrow(ax, (cx, y0), (cx, y1))
    step(ax, cx + 3.2, (y0 + y1) / 2, n, INK)
    ax.text(cx + 5.6, (y0 + y1) / 2, lab, ha="left", va="center", fontsize=7.2, color=INK, style="italic")
# Mutter drives both displays
arrow(ax, (X + W, 23), (82, 39), color=C[2])
ax.text(80.0, 28.6, "only output", ha="left", va="center", fontsize=7.2, color=C[2], style="italic")
arrow(ax, (X + W, 19.5), (82, 19.5), color=GRAY, ls="--")
ax.text(78, 21.2, "off", ha="center", va="center", fontsize=7.2, color=GRAY, style="italic")
# 5 capture
arrow(ax, (82, 45), (X + W, 47.5), color=C[0])
ax.text(77.6, 50.4, "5 capture", ha="center", va="center", fontsize=7.2, color=C[0], style="italic")

fig.savefig(HERE / "fig1-how-it-works.svg", metadata={"Date": None})
plt.close(fig)
