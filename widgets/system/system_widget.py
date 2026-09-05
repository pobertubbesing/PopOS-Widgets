#!/usr/bin/python3
"""Compact macOS-inspired system monitor for the COSMIC desktop."""

import json
import os
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

APP_ID = "com.local.CosmicSystemWidget"
CONFIG_PATH = Path.home() / ".config/cosmic-system-widget/config.json"
SIZE_PRESETS = {"small": (210, 210, 18), "medium": (280, 280, 22), "large": (350, 350, 28)}
SNAP_GRID = 8


def read_config():
    config = {"size": "small", "anchor": "top-right", "margin_x": 24, "margin_y": 286}
    try:
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        pass
    return config


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def cpu_percent():
    def read():
        values = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:]))
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    first = read()
    time.sleep(0.08)
    second = read()
    total = second[0] - first[0]
    return round(100 * (1 - (second[1] - first[1]) / total)) if total else 0


def memory_percent():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.split()[0])
    total = values.get("MemTotal", 1)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return round(100 * (total - available) / total)


class SystemWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title="System Monitor")
        self.config = read_config()
        self.size_name = self.config.get("size", "small")
        if self.size_name not in SIZE_PRESETS:
            self.size_name = "small"
        self.anchor = self.config.get("anchor", "top-right")
        self.margin_x = int(self.config.get("margin_x", 24))
        self.margin_y = int(self.config.get("margin_y", 286))
        self.drag_start = (self.margin_x, self.margin_y)
        self.set_name("system-window")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_accept_focus(False)
        self.set_app_paintable(True)
        screen = self.get_screen()
        if screen and screen.get_rgba_visual():
            self.set_visual(screen.get_rgba_visual())
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, APP_ID)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, self.anchor.startswith("top"))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, self.anchor.startswith("bottom"))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, self.anchor.endswith("left"))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, self.anchor.endswith("right"))
        edge = GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM
        side = GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT
        GtkLayerShell.set_margin(self, edge, self.margin_y)
        GtkLayerShell.set_margin(self, side, self.margin_x)
        self._install_css()
        self.card = Gtk.EventBox()
        self.card.set_name("system-card")
        self.card.connect("realize", lambda w: w.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.HAND1)))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.card.add(content)
        self.title = Gtk.Label(label="SYSTEM MONITOR", xalign=0)
        self.title.get_style_context().add_class("title")
        content.pack_start(self.title, False, False, 0)
        self.cpu = self._metric(content, "CPU")
        self.memory = self._metric(content, "MEMORY")
        self.disk = self._metric(content, "DISK")
        self.load = self._metric(content, "LOAD")
        self.add(self.card)
        self.card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.card.connect("button-press-event", self._button_press)
        self.drag = Gtk.GestureDrag.new(self.card)
        self.drag.set_button(1)
        self.drag.connect("drag-begin", self._drag_begin)
        self.drag.connect("drag-update", self._drag_update)
        self.drag.connect("drag-end", self._drag_end)
        self._apply_size(self.size_name, False)
        self.refresh()
        GLib.timeout_add_seconds(3, self.refresh)

    @staticmethod
    def _metric(parent, label):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = Gtk.Label(label=label, xalign=0)
        name.get_style_context().add_class("metric-name")
        value = Gtk.Label(label="--", xalign=1)
        value.get_style_context().add_class("metric-value")
        row.pack_start(name, True, True, 0)
        row.pack_end(value, False, False, 0)
        parent.pack_start(row, False, False, 0)
        return value

    def _install_css(self):
        css = b'''#system-window { background: transparent; } #system-card { background-image: linear-gradient(145deg, rgba(251,251,253,.90), rgba(226,228,233,.86)); border: 1px solid rgba(255,255,255,.58); border-radius: 24px; box-shadow: 0 14px 32px rgba(0,0,0,.28); color: #1c1c1e; font-family: Inter, "SF Pro Display", sans-serif; } .title { color: #ff3b30; font-size: 16px; font-weight: 800; letter-spacing: .5px; } .metric-name { color: rgba(28,28,30,.52); font-size: 11px; font-weight: 700; } .metric-value { color: #1c1c1e; font-size: 16px; font-weight: 700; } #system-card.widget-medium { border-radius: 30px; } #system-card.widget-medium .title { font-size: 21px; } #system-card.widget-medium .metric-name { font-size: 14px; } #system-card.widget-medium .metric-value { font-size: 21px; } #system-card.widget-large { border-radius: 36px; } #system-card.widget-large .title { font-size: 26px; } #system-card.widget-large .metric-name { font-size: 17px; } #system-card.widget-large .metric-value { font-size: 26px; }'''
        provider = Gtk.CssProvider(); provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def refresh(self):
        try:
            self.cpu.set_text(f"{cpu_percent()}%")
            self.memory.set_text(f"{memory_percent()}%")
            disk = os.statvfs(Path.home())
            used = 100 * (1 - disk.f_bavail / disk.f_blocks)
            self.disk.set_text(f"{used:.0f}%")
            self.load.set_text(f"{os.getloadavg()[0]:.2f}")
        except (OSError, ValueError):
            pass
        return True

    def _apply_size(self, name, save=True):
        self.size_name = name if name in SIZE_PRESETS else "small"
        width, height, margin = SIZE_PRESETS[self.size_name]
        style = self.card.get_style_context()
        for cls in ("widget-small", "widget-medium", "widget-large"): style.remove_class(cls)
        style.add_class(f"widget-{self.size_name}")
        self.card.set_size_request(width, height); self.set_default_size(width, height); self.resize(width, height)
        self.card.get_child().set_margin_top(margin); self.card.get_child().set_margin_bottom(margin)
        self.card.get_child().set_margin_start(margin); self.card.get_child().set_margin_end(margin)
        self.config["size"] = self.size_name
        if save: save_config(self.config)

    def _button_press(self, _widget, event):
        if event.button != 3: return False
        menu = Gtk.Menu(); heading = Gtk.MenuItem(label="Widget Size"); heading.set_sensitive(False); menu.append(heading)
        first = None
        for name, label in (("small", "Small"), ("medium", "Medium"), ("large", "Large")):
            item = Gtk.RadioMenuItem.new_with_label(None, label) if first is None else Gtk.RadioMenuItem.new_with_label_from_widget(first, label)
            if first is None: first = item
            item.set_active(name == self.size_name); item.connect("toggled", lambda i, n: i.get_active() and self._apply_size(n), name); menu.append(item)
        menu.append(Gtk.SeparatorMenuItem()); exit_item = Gtk.MenuItem(label="Exit Widget"); exit_item.connect("activate", lambda _i: self.destroy()); menu.append(exit_item)
        menu.show_all(); menu.popup_at_pointer(event); return True

    def _drag_begin(self, _gesture, _x, _y): self.drag_start = (self.margin_x, self.margin_y)
    def _drag_update(self, _gesture, dx, dy):
        self.margin_x = max(0, self.drag_start[0] - dx if self.anchor.endswith("right") else self.drag_start[0] + dx)
        self.margin_y = max(0, self.drag_start[1] + dy if self.anchor.startswith("top") else self.drag_start[1] - dy)
        edge = GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM; side = GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT
        GtkLayerShell.set_margin(self, edge, int(self.margin_y)); GtkLayerShell.set_margin(self, side, int(self.margin_x))
    def _drag_end(self, _gesture, _x, _y):
        self.margin_x = round(self.margin_x / SNAP_GRID) * SNAP_GRID; self.margin_y = round(self.margin_y / SNAP_GRID) * SNAP_GRID
        self.config.update({"margin_x": self.margin_x, "margin_y": self.margin_y}); save_config(self.config)


if __name__ == "__main__":
    win = SystemWidget(); win.connect("destroy", Gtk.main_quit); win.show_all(); Gtk.main()
