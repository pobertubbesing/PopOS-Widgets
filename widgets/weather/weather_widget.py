#!/usr/bin/python3
"""Small Wayland-native weather card for the COSMIC desktop."""

import json
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango


APP_ID = "com.local.CosmicWeatherWidget"
CONFIG_PATH = Path.home() / ".config/cosmic-weather-widget/config.json"
ICON_DIR = Path(__file__).resolve().parent / "icons"
REFRESH_SECONDS = 15 * 60
ICON_CACHE = {}
SNAP_GRID = 8
SNAP_DISTANCE = 16
WIDGET_GAP = 16
CALENDAR_CONFIG_PATH = Path.home() / ".config/cosmic-calendar-widget/config.json"
SIZE_PRESETS = {
    "small": {"width": 210, "height": 210, "margin": 12, "side_margin": 18, "icon": 42},
    "medium": {"width": 280, "height": 280, "margin": 22, "side_margin": 24, "icon": 54},
    "large": {"width": 350, "height": 350, "margin": 28, "side_margin": 30, "icon": 68},
}

WEATHER = {
    0: ("Sunny", "☀"),
    1: ("Mostly Sunny", "☀"),
    2: ("Partly Cloudy", "⛅"),
    3: ("Cloudy", "☁"),
    45: ("Fog", "≋"),
    48: ("Rime fog", "≋"),
    51: ("Light drizzle", "☂"),
    53: ("Drizzle", "☂"),
    55: ("Heavy drizzle", "☂"),
    56: ("Freezing drizzle", "☂"),
    57: ("Freezing drizzle", "☂"),
    61: ("Light rain", "☂"),
    63: ("Rain", "☂"),
    65: ("Heavy rain", "☂"),
    66: ("Freezing rain", "☂"),
    67: ("Freezing rain", "☂"),
    71: ("Light snow", "❄"),
    73: ("Snow", "❄"),
    75: ("Heavy snow", "❄"),
    77: ("Snow grains", "❄"),
    80: ("Rain showers", "☂"),
    81: ("Rain showers", "☂"),
    82: ("Heavy showers", "☂"),
    85: ("Snow showers", "❄"),
    86: ("Heavy snow showers", "❄"),
    95: ("Thunderstorm", "ϟ"),
    96: ("Storm with hail", "ϟ"),
    99: ("Storm with hail", "ϟ"),
}


def read_config():
    defaults = {
        "units": "imperial",
        "latitude": None,
        "longitude": None,
        "location_name": None,
        "auto_location": True,
        "size": "small",
        "anchor": "top-right",
        "margin_x": 24,
        "margin_y": 56,
    }
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        defaults.update(saved)
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "COSMIC desktop weather widget/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def locate(config):
    if not config.get("auto_location", True) and config.get("latitude") is not None and config.get("longitude") is not None:
        return (
            float(config["latitude"]),
            float(config["longitude"]),
            config.get("location_name") or "Local weather",
        )

    geo = fetch_json("https://ipwho.is/")
    if not geo.get("success", True):
        raise RuntimeError(geo.get("message", "automatic location failed"))
    place = geo.get("city") or geo.get("region")
    return float(geo["latitude"]), float(geo["longitude"]), place or "Local weather"


def geocode_location(query):
    params = {
        "name": query,
        "count": 1,
        "language": "en",
        "format": "json",
    }
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(params)
    results = fetch_json(url).get("results") or []
    if not results:
        raise ValueError("Location not found. Try a city, region, or postal code.")
    result = results[0]
    parts = [result.get("name"), result.get("admin1"), result.get("country")]
    label = ", ".join(part for index, part in enumerate(parts) if part and part not in parts[:index])
    return float(result["latitude"]), float(result["longitude"]), label


def fetch_weather(config):
    latitude, longitude, place = locate(config)
    imperial = config.get("units", "imperial").lower() == "imperial"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,weather_code,is_day"
        ),
        "daily": (
            "temperature_2m_max,temperature_2m_min"
        ),
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "timezone": "auto",
        "forecast_days": 1,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = fetch_json(url)
    data["place"] = place
    data["imperial"] = imperial
    return data


def condition(code, is_day=True):
    code = int(code)
    description, _icon = WEATHER.get(code, ("Weather", "●"))
    if code in (0, 1):
        if is_day:
            icon_name = "clear-day"
        else:
            description = "Clear" if code == 0 else "Mostly Clear"
            icon_name = "clear-night"
    elif code == 2:
        icon_name = "partly-cloudy-day" if is_day else "partly-cloudy-night"
    elif code == 3:
        icon_name = "cloudy"
    elif code in (45, 48):
        icon_name = "fog"
    elif code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        icon_name = "rain"
    elif code in (71, 73, 75, 77, 85, 86):
        icon_name = "snow"
    elif code in (95, 96, 99):
        icon_name = "storm"
    else:
        icon_name = "cloudy"
    return description, icon_name


def load_icon(icon_name, size):
    cache_key = (icon_name, size)
    if cache_key not in ICON_CACHE:
        ICON_CACHE[cache_key] = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(ICON_DIR / f"{icon_name}.svg"), size, size, True
        )
    return ICON_CACHE[cache_key]


def condition_style(code):
    code = int(code)
    if code in (0, 1):
        return "clear"
    if code in (2, 3):
        return "cloudy"
    if code in (45, 48):
        return "foggy"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rainy"
    if code in (71, 73, 75, 77, 85, 86):
        return "snowy"
    if code in (95, 96, 99):
        return "stormy"
    return "cloudy"


class WeatherCard(Gtk.Window):
    def __init__(self):
        super().__init__(title="Desktop Weather")
        self.config = read_config()
        self.refreshing = False
        self.anchor = self.config.get("anchor", "top-right")
        self.margin_x = int(self.config.get("margin_x", 24))
        self.margin_y = int(self.config.get("margin_y", 56))
        self.drag_start_margin_x = self.margin_x
        self.drag_start_margin_y = self.margin_y
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.current_icon_name = "clear-night"
        self.size_name = self.config.get("size", "small")
        if self.size_name not in SIZE_PRESETS:
            self.size_name = "small"
        initial_size = SIZE_PRESETS[self.size_name]

        self.set_name("weather-window")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_accept_focus(False)
        self.set_app_paintable(True)
        self.set_default_size(initial_size["width"], initial_size["height"])

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
        card = self._build_card()
        self.add(card)
        card.connect("size-allocate", self._on_size_allocate)
        card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        card.connect("button-press-event", self._on_button_press)
        self._apply_size(self.size_name, save=False)
        self.drag = Gtk.GestureDrag.new(card)
        self.drag.set_button(1)
        self.drag.connect("drag-begin", self._on_drag_begin)
        self.drag.connect("drag-update", self._on_drag_update)
        self.drag.connect("drag-end", self._on_drag_end)

        GLib.timeout_add_seconds(REFRESH_SECONDS, self.refresh)
        GLib.idle_add(self._initial_refresh)

    def _install_css(self):
        css = b"""
            #weather-window { background-color: transparent; }
            #weather-card {
                background-image: linear-gradient(145deg, rgba(71,127,194,0.88), rgba(36,83,147,0.88));
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 24px;
                box-shadow: 0 14px 32px rgba(0, 0, 0, 0.30);
                color: #ffffff;
                font-family: Inter, "SF Pro Display", sans-serif;
            }
            #weather-card.day.clear {
                background-image: linear-gradient(145deg, rgba(88,169,239,0.88), rgba(40,116,205,0.88));
            }
            #weather-card.night.clear {
                background-image: linear-gradient(145deg, rgba(36,77,131,0.88), rgba(16,29,58,0.88));
            }
            #weather-card.day.cloudy {
                background-image: linear-gradient(145deg, rgba(126,157,184,0.88), rgba(78,109,141,0.88));
            }
            #weather-card.night.cloudy {
                background-image: linear-gradient(145deg, rgba(64,83,109,0.88), rgba(29,41,61,0.88));
            }
            #weather-card.rainy {
                background-image: linear-gradient(145deg, rgba(80,120,150,0.88), rgba(38,62,88,0.88));
            }
            #weather-card.snowy {
                background-image: linear-gradient(145deg, rgba(145,181,205,0.88), rgba(88,119,143,0.88));
            }
            #weather-card.foggy {
                background-image: linear-gradient(145deg, rgba(131,147,162,0.88), rgba(77,89,103,0.88));
            }
            #weather-card.stormy {
                background-image: linear-gradient(145deg, rgba(77,73,106,0.88), rgba(36,36,61,0.88));
            }
            .place { color: rgba(255,255,255,0.98); font-size: 18px; font-weight: 700; }
            .temperature { color: #ffffff; font-size: 56px; font-weight: 300; }
            .condition { color: rgba(255,255,255,0.98); font-size: 14px; font-weight: 700; }
            .high-low { color: rgba(255,255,255,0.84); font-size: 13px; font-weight: 600; }
            #weather-card.widget-medium { border-radius: 30px; }
            #weather-card.widget-medium .place { font-size: 22px; }
            #weather-card.widget-medium .temperature { font-size: 74px; }
            #weather-card.widget-medium .condition { font-size: 17px; }
            #weather-card.widget-medium .high-low { font-size: 15px; }
            #weather-card.widget-large { border-radius: 36px; }
            #weather-card.widget-large .place { font-size: 26px; }
            #weather-card.widget-large .temperature { font-size: 92px; }
            #weather-card.widget-large .condition { font-size: 20px; }
            #weather-card.widget-large .high-low { font-size: 17px; }
            #weather-editor {
                background-color: rgba(247,247,249,0.97);
                border: 1px solid rgba(255,255,255,0.70);
                border-radius: 18px;
                box-shadow: 0 18px 42px rgba(0,0,0,0.34);
                color: #1c1c1e;
            }
            .edit-header { color: #1c1c1e; font-size: 16px; font-weight: 700; }
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
        card.set_name("weather-card")
        card.get_style_context().add_class("night")
        card.get_style_context().add_class("clear")
        card.connect("realize", self._set_drag_cursor)
        self.card = card
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(18)
        root.set_margin_end(18)
        root.set_halign(Gtk.Align.FILL)
        self.content = root
        card.add(root)

        location = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        location.set_halign(Gtk.Align.START)
        self.place = self._label("Finding local weather…", "place")
        self.place.set_ellipsize(Pango.EllipsizeMode.END)
        self.place.set_max_width_chars(14)
        self.location_marker = Gtk.Image.new_from_pixbuf(load_icon("location", 12))
        self.location_marker.set_valign(Gtk.Align.CENTER)
        location.pack_start(self.place, False, False, 0)
        location.pack_start(self.location_marker, False, False, 0)
        root.pack_start(location, False, False, 0)

        self.temperature = self._label("--°", "temperature", 0.0)
        self.temperature.set_halign(Gtk.Align.START)
        root.pack_start(self.temperature, False, False, 0)

        self.icon = Gtk.Image()
        self.icon.set_size_request(42, 42)
        self.icon.set_halign(Gtk.Align.START)
        root.pack_start(self.icon, False, False, 0)

        self.description = self._label("Loading", "condition", 0.0)
        self.description.set_halign(Gtk.Align.START)
        root.pack_start(self.description, False, False, 0)

        self.high_low = self._label("H:--°  L:--°", "high-low", 0.0)
        self.high_low.set_halign(Gtk.Align.START)
        root.pack_start(self.high_low, False, False, 0)
        return card

    def _save_config(self):
        try:
            save_config(self.config)
        except OSError as error:
            print(f"Could not save widget settings: {error}", flush=True)

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
        self.content.set_margin_start(preset["side_margin"])
        self.content.set_margin_end(preset["side_margin"])
        self.icon.set_size_request(preset["icon"], preset["icon"])
        self.icon.set_from_pixbuf(load_icon(self.current_icon_name, preset["icon"]))
        self.card.set_size_request(preset["width"], preset["height"])
        self.set_default_size(preset["width"], preset["height"])
        self.resize(preset["width"], preset["height"])
        if save:
            self._save_config()

    def _on_size_selected(self, item, size_name):
        if item.get_active() and size_name != self.size_name:
            self._apply_size(size_name)

    def _on_button_press(self, _widget, event):
        if event.button != Gdk.BUTTON_SECONDARY:
            return False

        menu = Gtk.Menu()
        size_heading = Gtk.MenuItem(label="Widget Size")
        size_heading.set_sensitive(False)
        menu.append(size_heading)

        first_size_item = None
        for size_name, label in (("small", "Small"), ("medium", "Medium"), ("large", "Large")):
            if first_size_item is None:
                item = Gtk.RadioMenuItem.new_with_label(None, label)
                first_size_item = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(first_size_item, label)
            item.set_active(size_name == self.size_name)
            item.connect("toggled", self._on_size_selected, size_name)
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())
        edit_item = Gtk.MenuItem(label="Edit…")
        edit_item.connect("activate", self._edit_weather)
        menu.append(edit_item)
        menu.append(Gtk.SeparatorMenuItem())
        exit_item = Gtk.MenuItem(label="Exit Widget")
        exit_item.connect("activate", lambda _item: self.destroy())
        menu.append(exit_item)
        menu.show_all()
        self.context_menu = menu
        menu.connect("deactivate", lambda _menu: setattr(self, "context_menu", None))
        menu.popup_at_pointer(event)
        return True

    def _edit_weather(self, _item):
        existing = getattr(self, "edit_dialog", None)
        if existing:
            existing.show()
            return

        dialog = Gtk.Dialog(
            title="Edit Weather",
            flags=Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dialog.set_name("weather-editor")
        dialog.set_decorated(False)
        dialog.set_resizable(False)
        dialog.set_accept_focus(True)
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.OK,
        )
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_default_size(390, 250)

        GtkLayerShell.init_for_window(dialog)
        GtkLayerShell.set_namespace(dialog, f"{APP_ID}.Editor")
        GtkLayerShell.set_layer(dialog, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(dialog, -1)
        GtkLayerShell.set_keyboard_mode(dialog, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_anchor(dialog, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(dialog, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(dialog, GtkLayerShell.Edge.BOTTOM, False)
        GtkLayerShell.set_anchor(dialog, GtkLayerShell.Edge.RIGHT, False)

        widget_width = self.card.get_allocated_width() or SIZE_PRESETS[self.size_name]["width"]
        widget_height = self.card.get_allocated_height() or SIZE_PRESETS[self.size_name]["height"]
        widget_x, widget_y = self._absolute_position(
            widget_width,
            widget_height,
            self.anchor,
            self.margin_x,
            self.margin_y,
        )
        screen_width, screen_height = self._screen_dimensions()
        panel_width, panel_height = 390, 250
        right_side = widget_x + widget_width + WIDGET_GAP
        if right_side + panel_width <= screen_width:
            panel_x = right_side
        else:
            panel_x = max(0, widget_x - panel_width - WIDGET_GAP)
        panel_y = max(0, min(widget_y, screen_height - panel_height))
        self.edit_margin_x = int(panel_x)
        self.edit_margin_y = int(panel_y)
        GtkLayerShell.set_margin(dialog, GtkLayerShell.Edge.LEFT, self.edit_margin_x)
        GtkLayerShell.set_margin(dialog, GtkLayerShell.Edge.TOP, self.edit_margin_y)

        body = dialog.get_content_area()
        body.set_spacing(14)
        body.set_margin_top(12)
        body.set_margin_bottom(18)
        body.set_margin_start(18)
        body.set_margin_end(18)

        header = Gtk.EventBox()
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_label = self._label("Weather Settings", "edit-header")
        close_button = Gtk.Button.new_with_label("×")
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        close_button.connect("clicked", lambda _button: dialog.response(Gtk.ResponseType.CANCEL))
        header_box.pack_start(header_label, True, True, 0)
        header_box.pack_end(close_button, False, False, 0)
        header.add(header_box)
        body.pack_start(header, False, False, 0)

        edit_drag = Gtk.GestureDrag.new(header)

        def edit_drag_begin(_gesture, _x, _y):
            self.edit_drag_start_x = self.edit_margin_x
            self.edit_drag_start_y = self.edit_margin_y

        def edit_drag_update(_gesture, offset_x, offset_y):
            self.edit_margin_x = max(
                0,
                min(screen_width - panel_width, self.edit_drag_start_x + int(offset_x)),
            )
            self.edit_margin_y = max(
                0,
                min(screen_height - panel_height, self.edit_drag_start_y + int(offset_y)),
            )
            GtkLayerShell.set_margin(dialog, GtkLayerShell.Edge.LEFT, self.edit_margin_x)
            GtkLayerShell.set_margin(dialog, GtkLayerShell.Edge.TOP, self.edit_margin_y)

        edit_drag.connect("drag-begin", edit_drag_begin)
        edit_drag.connect("drag-update", edit_drag_update)
        dialog.edit_drag = edit_drag

        auto_location = Gtk.CheckButton(label="Use current location automatically")
        auto_location.set_active(self.config.get("auto_location", True))
        body.pack_start(auto_location, False, False, 0)

        location_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        location_label = Gtk.Label(label="Location", xalign=0)
        location_entry = Gtk.Entry()
        location_entry.set_placeholder_text("City or postal code")
        location_entry.set_text(self.config.get("location_name") or "")
        location_entry.set_hexpand(True)
        location_grid.attach(location_label, 0, 0, 1, 1)
        location_grid.attach(location_entry, 1, 0, 1, 1)

        units_label = Gtk.Label(label="Temperature", xalign=0)
        units = Gtk.ComboBoxText()
        units.append("imperial", "Fahrenheit (°F)")
        units.append("metric", "Celsius (°C)")
        units.set_active_id(self.config.get("units", "imperial"))
        location_grid.attach(units_label, 0, 1, 1, 1)
        location_grid.attach(units, 1, 1, 1, 1)
        body.pack_start(location_grid, False, False, 0)

        tracking_note = Gtk.Label(
            label="Automatic location updates from your network every 15 minutes.",
            xalign=0,
        )
        tracking_note.set_line_wrap(True)
        tracking_note.get_style_context().add_class("dim-label")
        body.pack_start(tracking_note, False, False, 0)

        error_label = Gtk.Label(xalign=0)
        error_label.set_line_wrap(True)
        error_label.get_style_context().add_class("error")
        body.pack_start(error_label, False, False, 0)

        def update_location_controls(check_button):
            automatic = check_button.get_active()
            location_label.set_sensitive(not automatic)
            location_entry.set_sensitive(not automatic)

        auto_location.connect("toggled", update_location_controls)
        update_location_controls(auto_location)
        self.edit_dialog = dialog

        def finish_edit(_dialog, response):
            if response == Gtk.ResponseType.OK:
                automatic = auto_location.get_active()
                if automatic:
                    latitude = longitude = location_name = None
                else:
                    query = location_entry.get_text().strip()
                    if not query:
                        error_label.set_text("Enter a city or postal code.")
                        return
                    try:
                        latitude, longitude, location_name = geocode_location(query)
                    except Exception as error:
                        error_label.set_text(str(error))
                        return

                self.config.update({
                    "auto_location": automatic,
                    "latitude": latitude,
                    "longitude": longitude,
                    "location_name": location_name,
                    "units": units.get_active_id() or "imperial",
                })
                self.location_marker.set_visible(automatic)
                self._save_config()
                self.refresh()
            dialog.destroy()

        def clear_edit_dialog(_dialog):
            self.edit_dialog = None

        dialog.connect("response", finish_edit)
        dialog.connect("destroy", clear_edit_dialog)
        dialog.show_all()

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
            peer = json.loads(CALENDAR_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        peer_sizes = {"small": (210, 210), "medium": (280, 280), "large": (350, 350)}
        default_width, default_height = peer_sizes.get(
            peer.get("size", "small"), peer_sizes["small"]
        )
        width = int(peer.get("actual_width", default_width))
        height = int(peer.get("actual_height", default_height))
        anchor = peer.get("anchor", "top-left")
        x, y = self._absolute_position(
            width,
            height,
            anchor,
            int(peer.get("margin_x", 286)),
            int(peer.get("margin_y", 66)),
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
            self.refresh()
            return
        self.config["margin_x"] = self.margin_x
        self.config["margin_y"] = self.margin_y
        self._save_config()

    def _initial_refresh(self):
        self.refresh()
        return False

    def refresh(self):
        if self.refreshing:
            return True
        self.refreshing = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()
        return True

    def _fetch_worker(self):
        try:
            data = fetch_weather(self.config)
            GLib.idle_add(self._apply_weather, data)
        except Exception as error:
            GLib.idle_add(self._show_error, str(error))

    def _apply_weather(self, data):
        current = data["current"]
        daily = data["daily"]
        description, icon_name = condition(current["weather_code"], current.get("is_day", 1))
        self.current_icon_name = icon_name
        self.place.set_text(data["place"])
        icon_size = SIZE_PRESETS[self.size_name]["icon"]
        self.icon.set_from_pixbuf(load_icon(icon_name, icon_size))
        self.location_marker.set_visible(self.config.get("auto_location", True))
        self.temperature.set_text(f"{round(current['temperature_2m'])}°")
        self.description.set_text(description)
        self.high_low.set_text(
            f"H:{round(daily['temperature_2m_max'][0])}°  "
            f"L:{round(daily['temperature_2m_min'][0])}°"
        )
        style = self.card.get_style_context()
        for css_class in ("day", "night", "clear", "cloudy", "rainy", "snowy", "foggy", "stormy"):
            style.remove_class(css_class)
        style.add_class("day" if current.get("is_day", 1) else "night")
        style.add_class(condition_style(current["weather_code"]))

        self.refreshing = False
        return False

    def _show_error(self, message):
        self.description.set_text("Weather unavailable")
        print(f"Weather update failed: {message}", flush=True)
        self.refreshing = False
        return False


def main():
    Gtk.init()
    window = WeatherCard()
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()

