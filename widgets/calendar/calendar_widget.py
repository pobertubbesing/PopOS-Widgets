#!/usr/bin/python3
"""macOS-inspired calendar widget for the COSMIC desktop."""

import calendar
import json
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell


APP_ID = "com.local.CosmicCalendarWidget"
CONFIG_PATH = Path.home() / ".config/cosmic-calendar-widget/config.json"
WEATHER_CONFIG_PATH = Path.home() / ".config/cosmic-weather-widget/config.json"
SNAP_GRID = 8
SNAP_DISTANCE = 16
WIDGET_GAP = 16
SIZE_PRESETS = {
    "small": {"width": 210, "height": 210, "margin": 14, "day": 22},
    "medium": {"width": 280, "height": 280, "margin": 20, "day": 31},
    "large": {"width": 350, "height": 350, "margin": 26, "day": 39},
}


def read_config():
    config = {
        "size": "small",
        "anchor": "top-left",
        "margin_x": 286,
        "margin_y": 66,
    }
    try:
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        pass
    return config


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


class CalendarWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title="Desktop Calendar")
        self.config = read_config()
        self.size_name = self.config.get("size", "small")
        if self.size_name not in SIZE_PRESETS:
            self.size_name = "small"
        self.anchor = self.config.get("anchor", "top-left")
        self.margin_x = int(self.config.get("margin_x", 286))
        self.margin_y = int(self.config.get("margin_y", 66))
        self.drag_start_margin_x = self.margin_x
        self.drag_start_margin_y = self.margin_y
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.displayed_date = None

        preset = SIZE_PRESETS[self.size_name]
        self.set_name("calendar-window")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_accept_focus(False)
        self.set_app_paintable(True)
        self.set_default_size(preset["width"], preset["height"])

        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen else None
        if visual:
            self.set_visual(visual)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, APP_ID)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, self.anchor.startswith("top"))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, self.anchor.startswith("bottom"))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, self.anchor.endswith("left"))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, self.anchor.endswith("right"))
        GtkLayerShell.set_margin(
            self,
            GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM,
            self.margin_y,
        )
        GtkLayerShell.set_margin(
            self,
            GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT,
            self.margin_x,
        )

        self._install_css()
        self.card = self._build_card()
        self.add(self.card)
        self.card.connect("size-allocate", self._on_size_allocate)
        self.card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.card.connect("button-press-event", self._on_button_press)
        self._apply_size(self.size_name, save=False)

        self.drag = Gtk.GestureDrag.new(self.card)
        self.drag.set_button(1)
        self.drag.connect("drag-begin", self._on_drag_begin)
        self.drag.connect("drag-update", self._on_drag_update)
        self.drag.connect("drag-end", self._on_drag_end)

        self.refresh()
        GLib.timeout_add_seconds(60, self.refresh)

    def _install_css(self):
        css = b"""
            #calendar-window { background-color: transparent; }
            #calendar-card {
                background-image: linear-gradient(145deg, rgba(251,251,253,0.90), rgba(226,228,233,0.88));
                border: 1px solid rgba(255,255,255,0.58);
                border-radius: 24px;
                box-shadow: 0 14px 32px rgba(0,0,0,0.28);
                color: #1c1c1e;
                font-family: Inter, "SF Pro Display", sans-serif;
            }
            .month-name { color: #ff3b30; font-size: 20px; font-weight: 700; }
            .weekday { color: rgba(28,28,30,0.48); font-size: 10px; font-weight: 700; }
            .day { color: rgba(28,28,30,0.88); font-size: 12px; font-weight: 600; }
            .today { background-color: #ff3b30; color: #ffffff; border-radius: 999px; font-weight: 800; }
            #calendar-card.widget-medium { border-radius: 30px; }
            #calendar-card.widget-medium .month-name { font-size: 26px; }
            #calendar-card.widget-medium .weekday { font-size: 12px; }
            #calendar-card.widget-medium .day { font-size: 15px; }
            #calendar-card.widget-large { border-radius: 36px; }
            #calendar-card.widget-large .month-name { font-size: 32px; }
            #calendar-card.widget-large .weekday { font-size: 14px; }
            #calendar-card.widget-large .day { font-size: 18px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    @staticmethod
    def _label(text="", css_class=None, xalign=0.0):
        label = Gtk.Label(label=text, xalign=xalign)
        if css_class:
            label.get_style_context().add_class(css_class)
        return label

    def _build_card(self):
        card = Gtk.EventBox()
        card.set_name("calendar-card")
        card.connect("realize", self._set_drag_cursor)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.content = content
        card.add(content)

        self.month_name = self._label("SEPTEMBER", "month-name")
        self.month_name.set_halign(Gtk.Align.START)
        content.pack_start(self.month_name, False, False, 0)

        self.calendar_grid = Gtk.Grid()
        self.calendar_grid.set_column_homogeneous(True)
        self.calendar_grid.set_row_homogeneous(True)
        self.calendar_grid.set_hexpand(True)
        self.calendar_grid.set_vexpand(True)
        content.pack_start(self.calendar_grid, True, True, 0)
        return card

    def _build_month(self, now):
        for child in self.calendar_grid.get_children():
            self.calendar_grid.remove(child)

        for column, name in enumerate(("S", "M", "T", "W", "T", "F", "S")):
            label = self._label(name, "weekday", 0.5)
            self.calendar_grid.attach(label, column, 0, 1, 1)

        weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(now.year, now.month)

        cell_size = SIZE_PRESETS[self.size_name]["day"]
        for row, week in enumerate(weeks, start=1):
            for column, day in enumerate(week):
                label = self._label(str(day) if day else "", "day", 0.5)
                label.set_halign(Gtk.Align.CENTER)
                label.set_valign(Gtk.Align.CENTER)
                label.set_size_request(cell_size, cell_size)
                if day == now.day:
                    label.get_style_context().add_class("today")
                self.calendar_grid.attach(label, column, row, 1, 1)
        self.calendar_grid.show_all()

    def refresh(self):
        now = datetime.now().astimezone()
        self.month_name.set_text(now.strftime("%B"))
        date_key = (now.year, now.month, now.day, self.size_name)
        if date_key != self.displayed_date:
            self._build_month(now)
            self.displayed_date = date_key
        return True

    def _save_config(self):
        try:
            save_config(self.config)
        except OSError as error:
            print(f"Could not save calendar settings: {error}", flush=True)

    def _apply_size(self, size_name, save=True):
        if size_name not in SIZE_PRESETS:
            size_name = "small"
        preset = SIZE_PRESETS[size_name]
        self.size_name = size_name
        self.config["size"] = size_name
        style = self.card.get_style_context()
        for css_class in ("widget-small", "widget-medium", "widget-large"):
            style.remove_class(css_class)
        style.add_class(f"widget-{size_name}")
        self.content.set_margin_top(preset["margin"])
        self.content.set_margin_bottom(preset["margin"])
        self.content.set_margin_start(preset["margin"])
        self.content.set_margin_end(preset["margin"])
        self.card.set_size_request(preset["width"], preset["height"])
        self.set_default_size(preset["width"], preset["height"])
        self.resize(preset["width"], preset["height"])
        self.displayed_date = None
        self.refresh()
        if save:
            self._save_config()

    def _on_size_selected(self, item, size_name):
        if item.get_active() and size_name != self.size_name:
            self._apply_size(size_name)

    def _on_button_press(self, _widget, event):
        if event.button != Gdk.BUTTON_SECONDARY:
            return False
        menu = Gtk.Menu()
        heading = Gtk.MenuItem(label="Widget Size")
        heading.set_sensitive(False)
        menu.append(heading)
        first_item = None
        for size_name, label in (("small", "Small"), ("medium", "Medium"), ("large", "Large")):
            if first_item is None:
                item = Gtk.RadioMenuItem.new_with_label(None, label)
                first_item = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(first_item, label)
            item.set_active(size_name == self.size_name)
            item.connect("toggled", self._on_size_selected, size_name)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        exit_item = Gtk.MenuItem(label="Exit Widget")
        exit_item.connect("activate", lambda _item: self.destroy())
        menu.append(exit_item)
        menu.show_all()
        self.context_menu = menu
        menu.connect("deactivate", lambda _menu: setattr(self, "context_menu", None))
        menu.popup_at_pointer(event)
        return True

    def _set_drag_cursor(self, widget):
        cursor = Gdk.Cursor.new_from_name(widget.get_display(), "move")
        if widget.get_window() and cursor:
            widget.get_window().set_cursor(cursor)

    def _on_size_allocate(self, _widget, allocation):
        width, height = allocation.width, allocation.height
        if (
            self.config.get("actual_width") != width
            or self.config.get("actual_height") != height
        ):
            self.config["actual_width"] = width
            self.config["actual_height"] = height
            self._save_config()

    def _on_drag_begin(self, _gesture, _start_x, _start_y):
        self.drag_start_margin_x = self.margin_x
        self.drag_start_margin_y = self.margin_y
        self.drag_offset_x = 0
        self.drag_offset_y = 0

    def _on_drag_update(self, _gesture, offset_x, offset_y):
        self.drag_offset_x = int(offset_x)
        self.drag_offset_y = int(offset_y)
        horizontal_direction = 1 if self.anchor.endswith("left") else -1
        vertical_direction = 1 if self.anchor.startswith("top") else -1
        self.margin_x = max(0, self.drag_start_margin_x + horizontal_direction * self.drag_offset_x)
        self.margin_y = max(0, self.drag_start_margin_y + vertical_direction * self.drag_offset_y)
        self._snap_position()

    def _screen_dimensions(self):
        screen = self.get_screen()
        return screen.get_width(), screen.get_height()

    def _absolute_position(self, width, height, anchor, margin_x, margin_y):
        screen_width, screen_height = self._screen_dimensions()
        x = margin_x if anchor.endswith("left") else screen_width - margin_x - width
        y = margin_y if anchor.startswith("top") else screen_height - margin_y - height
        return x, y

    @staticmethod
    def _nearest_snap(value, candidates):
        nearby = [(abs(value - candidate), candidate) for candidate in candidates]
        distance, candidate = min(nearby, default=(SNAP_DISTANCE + 1, value))
        return candidate if distance <= SNAP_DISTANCE else round(value / SNAP_GRID) * SNAP_GRID

    def _peer_rectangle(self):
        try:
            peer = json.loads(WEATHER_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        peer_sizes = {"small": (210, 210), "medium": (280, 280), "large": (350, 350)}
        default_width, default_height = peer_sizes.get(
            peer.get("size", "small"), peer_sizes["small"]
        )
        width = int(peer.get("actual_width", default_width))
        height = int(peer.get("actual_height", default_height))
        anchor = peer.get("anchor", "top-right")
        x, y = self._absolute_position(
            width,
            height,
            anchor,
            int(peer.get("margin_x", 24)),
            int(peer.get("margin_y", 56)),
        )
        return x, y, width, height

    def _snap_position(self):
        preset = SIZE_PRESETS[self.size_name]
        width = self.card.get_allocated_width() or preset["width"]
        height = self.card.get_allocated_height() or preset["height"]
        x, y = self._absolute_position(
            width, height, self.anchor, self.margin_x, self.margin_y
        )
        peer = self._peer_rectangle()
        if peer:
            peer_x, peer_y, peer_width, peer_height = peer
            x = self._nearest_snap(x, (
                peer_x,
                peer_x + peer_width - width,
                peer_x - width - WIDGET_GAP,
                peer_x + peer_width + WIDGET_GAP,
            ))
            y = self._nearest_snap(y, (
                peer_y,
                peer_y + peer_height - height,
                peer_y - height - WIDGET_GAP,
                peer_y + peer_height + WIDGET_GAP,
            ))
        else:
            x = round(x / SNAP_GRID) * SNAP_GRID
            y = round(y / SNAP_GRID) * SNAP_GRID

        screen_width, screen_height = self._screen_dimensions()
        x = max(0, min(x, screen_width - width))
        y = max(0, min(y, screen_height - height))
        self.margin_x = x if self.anchor.endswith("left") else screen_width - x - width
        self.margin_y = y if self.anchor.startswith("top") else screen_height - y - height
        GtkLayerShell.set_margin(
            self,
            GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT,
            self.margin_x,
        )
        GtkLayerShell.set_margin(
            self,
            GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM,
            self.margin_y,
        )

    def _on_drag_end(self, _gesture, _offset_x, _offset_y):
        if abs(self.drag_offset_x) < 4 and abs(self.drag_offset_y) < 4:
            return
        self.config["margin_x"] = self.margin_x
        self.config["margin_y"] = self.margin_y
        self._save_config()


def main():
    Gtk.init()
    widget = CalendarWidget()
    widget.connect("destroy", Gtk.main_quit)
    widget.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()

