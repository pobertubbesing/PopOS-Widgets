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
SNAP_DISTANCE = 16
WIDGET_GAP = 16


def read_config():
    config = {"size": "small", "units": "celsius", "anchor": "top-right", "margin_x": 24, "margin_y": 286}
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


def network_bytes():
    received = sent = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        if ":" not in line:
            continue
        interface, values = line.split(":", 1)
        if interface.strip() == "lo":
            continue
        fields = values.split()
        if len(fields) >= 9:
            received += int(fields[0])
            sent += int(fields[8])
    return received, sent


def format_rate(bytes_per_second):
    bits = float(bytes_per_second) * 8
    if bits >= 1_000_000_000:
        value, label = bits / 1_000_000_000, "Gbps"
    elif bits >= 1_000_000:
        value, label = bits / 1_000_000, "Mbps"
    else:
        value, label = float(bytes_per_second), "B/s"
    return f"{value:.0f} {label}" if value >= 10 else f"{value:.1f} {label}"


def temperature_celsius():
    readings = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = int(path.read_text().strip()) / 1000
            if -20 < value < 150:
                readings.append(value)
        except (OSError, ValueError):
            continue
    return max(readings) if readings else None


class SystemWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title="System Monitor")
        self.config = read_config()
        self.size_name = self.config.get("size", "small")
        self.units = self.config.get("units", "celsius")
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
        self.cpu = self._metric(content, "◉", "CPU")
        self.memory = self._metric(content, "▦", "MEMORY")
        self.load = self._metric(content, "↯", "LOAD")
        self.download = self._metric(content, "↓", "DOWNLOAD")
        self.upload = self._metric(content, "↑", "UPLOAD")
        self.temperature = self._metric(content, "♨", "TEMP")
        self.net_previous = (time.monotonic(), *network_bytes())
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
    def _metric(parent, icon, label):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        symbol = Gtk.Label(label=icon, xalign=0)
        symbol.get_style_context().add_class("metric-icon")
        name = Gtk.Label(label=label, xalign=0)
        name.get_style_context().add_class("metric-name")
        value = Gtk.Label(label="--", xalign=1)
        value.get_style_context().add_class("metric-value")
        row.pack_start(symbol, False, False, 0)
        row.pack_start(name, True, True, 0)
        row.pack_end(value, False, False, 0)
        parent.pack_start(row, False, False, 0)
        return value

    def _install_css(self):
        css = b'''#system-window { background: transparent; } #system-card { background-image: linear-gradient(145deg, rgba(251,251,253,.90), rgba(226,228,233,.86)); border: 1px solid rgba(255,255,255,.58); border-radius: 24px; box-shadow: 0 14px 32px rgba(0,0,0,.28); color: #1c1c1e; font-family: Inter, "SF Pro Display", sans-serif; } .title { color: #ff3b30; font-size: 16px; font-weight: 800; letter-spacing: .5px; } .metric-icon { color: #ff3b30; font-size: 15px; font-weight: 800; min-width: 18px; } .metric-name { color: rgba(28,28,30,.52); font-size: 11px; font-weight: 700; } .metric-value { color: #1c1c1e; font-size: 16px; font-weight: 700; } #system-card.widget-medium { border-radius: 30px; } #system-card.widget-medium .title { font-size: 21px; } #system-card.widget-medium .metric-icon { font-size: 19px; } #system-card.widget-medium .metric-name { font-size: 14px; } #system-card.widget-medium .metric-value { font-size: 21px; } #system-card.widget-large { border-radius: 36px; } #system-card.widget-large .title { font-size: 26px; } #system-card.widget-large .metric-icon { font-size: 23px; } #system-card.widget-large .metric-name { font-size: 17px; } #system-card.widget-large .metric-value { font-size: 26px; }'''
        provider = Gtk.CssProvider(); provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def refresh(self):
        try:
            self.cpu.set_text(f"{cpu_percent()}%")
            self.memory.set_text(f"{memory_percent()}%")
            self.load.set_text(f"{os.getloadavg()[0]:.2f}")
            now = time.monotonic(); received, sent = network_bytes()
            elapsed = max(0.1, now - self.net_previous[0])
            self.download.set_text(format_rate((received - self.net_previous[1]) / elapsed))
            self.upload.set_text(format_rate((sent - self.net_previous[2]) / elapsed))
            self.net_previous = (now, received, sent)
            temperature = temperature_celsius()
            if temperature is None:
                self.temperature.set_text("N/A")
            elif self.units == "fahrenheit":
                self.temperature.set_text(f"{temperature * 9 / 5 + 32:.0f} °F")
            else:
                self.temperature.set_text(f"{temperature:.0f} °C")
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
        menu.append(Gtk.SeparatorMenuItem())
        edit_item = Gtk.MenuItem(label="Edit…"); edit_item.connect("activate", self._edit); menu.append(edit_item)
        exit_item = Gtk.MenuItem(label="Exit Widget"); exit_item.connect("activate", lambda _i: self.destroy()); menu.append(exit_item)
        menu.show_all(); menu.popup_at_pointer(event); return True

    def _edit(self, _item):
        dialog = Gtk.Dialog(title="System Monitor Settings", transient_for=self, modal=True)
        dialog.set_position(Gtk.WindowPosition.MOUSE)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL); dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area(); box.set_spacing(10); box.set_border_width(18)
        label = Gtk.Label(label="Temperature units", xalign=0); box.pack_start(label, False, False, 0)
        combo = Gtk.ComboBoxText(); combo.append("celsius", "Celsius (°C)"); combo.append("fahrenheit", "Fahrenheit (°F)"); combo.set_active_id(self.units); box.pack_start(combo, False, False, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK and combo.get_active_id():
            self.units = combo.get_active_id(); self.config["units"] = self.units; save_config(self.config); self.refresh()
        dialog.destroy()

    def _drag_begin(self, _gesture, _x, _y): self.drag_start = (self.margin_x, self.margin_y); self.drag_offset = (0, 0)
    def _drag_update(self, _gesture, dx, dy):
        self.drag_offset = (dx, dy)
        self.margin_x = max(0, self.drag_start[0] - dx if self.anchor.endswith("right") else self.drag_start[0] + dx)
        self.margin_y = max(0, self.drag_start[1] + dy if self.anchor.startswith("top") else self.drag_start[1] - dy)
        self._snap_position()
        edge = GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM; side = GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT
        GtkLayerShell.set_margin(self, edge, int(self.margin_y)); GtkLayerShell.set_margin(self, side, int(self.margin_x))
    def _screen_dimensions(self):
        screen = self.get_screen(); return screen.get_width(), screen.get_height()

    def _absolute_position(self, width, height, anchor, margin_x, margin_y):
        sw, sh = self._screen_dimensions()
        return (margin_x if anchor.endswith("left") else sw - margin_x - width,
                margin_y if anchor.startswith("top") else sh - margin_y - height)

    def _peer_rectangle(self):
        for path, default_anchor, default_x, default_y in ((Path.home() / ".config/cosmic-weather-widget/config.json", "top-right", 24, 60), (Path.home() / ".config/cosmic-calendar-widget/config.json", "top-left", 286, 66)):
            try: peer = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError): continue
            size = peer.get("size", "small"); width = int(peer.get("actual_width", SIZE_PRESETS.get(size, SIZE_PRESETS["small"])[0])); height = int(peer.get("actual_height", SIZE_PRESETS.get(size, SIZE_PRESETS["small"])[1]))
            x, y = self._absolute_position(width, height, peer.get("anchor", default_anchor), int(peer.get("margin_x", default_x)), int(peer.get("margin_y", default_y)))
            return x, y, width, height
        return None

    def _snap_position(self):
        width, height = SIZE_PRESETS[self.size_name][:2]; x, y = self._absolute_position(width, height, self.anchor, self.margin_x, self.margin_y); peer = self._peer_rectangle()
        if peer:
            px, py, pw, ph = peer
            x_candidates = (px, px + pw - width, px - width - WIDGET_GAP, px + pw + WIDGET_GAP)
            y_candidates = (py, py + ph - height, py - height - WIDGET_GAP, py + ph + WIDGET_GAP)
            nearest_x = min(x_candidates, key=lambda v: abs(v - x)); nearest_y = min(y_candidates, key=lambda v: abs(v - y))
            if abs(nearest_x - x) <= SNAP_DISTANCE: x = nearest_x
            if abs(nearest_y - y) <= SNAP_DISTANCE: y = nearest_y
        x, y = round(x / SNAP_GRID) * SNAP_GRID, round(y / SNAP_GRID) * SNAP_GRID
        sw, sh = self._screen_dimensions(); x, y = max(0, min(x, sw - width)), max(0, min(y, sh - height))
        self.margin_x = x if self.anchor.endswith("left") else sw - x - width; self.margin_y = y if self.anchor.startswith("top") else sh - y - height
        side = GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT; edge = GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM
        GtkLayerShell.set_margin(self, side, self.margin_x); GtkLayerShell.set_margin(self, edge, self.margin_y)

    def _drag_end(self, _gesture, _x, _y):
        self._snap_position()
        self.config.update({"margin_x": self.margin_x, "margin_y": self.margin_y}); save_config(self.config)


if __name__ == "__main__":
    win = SystemWidget(); win.connect("destroy", Gtk.main_quit); win.show_all(); Gtk.main()
