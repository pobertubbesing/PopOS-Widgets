#!/usr/bin/python3
"""Spotify MPRIS controller widget for the COSMIC desktop."""
import json
import urllib.error
import urllib.request
from pathlib import Path
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell

CONFIG_PATH = Path.home() / ".config/cosmic-spotify-widget/config.json"
APP_ID = "com.local.CosmicSpotifyWidget"
SIZES = {"small": (260, 150, 16), "medium": (340, 190, 20), "large": (430, 240, 24)}
SNAP_GRID = 8

def config():
    value = {"size": "small", "anchor": "top-left", "margin_x": 24, "margin_y": 820}
    try: value.update(json.loads(CONFIG_PATH.read_text()))
    except (OSError, ValueError, TypeError): pass
    return value

def save(value):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True); CONFIG_PATH.write_text(json.dumps(value, indent=2) + "\n")

class SpotifyWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title="Spotify")
        self.config = config(); self.size_name = self.config.get("size", "small")
        if self.size_name not in SIZES: self.size_name = "small"
        self.anchor = self.config.get("anchor", "top-left"); self.mx = int(self.config.get("margin_x", 24)); self.my = int(self.config.get("margin_y", 820))
        self.set_decorated(False); self.set_resizable(False); self.set_accept_focus(False); self.set_app_paintable(True)
        if self.get_screen() and self.get_screen().get_rgba_visual(): self.set_visual(self.get_screen().get_rgba_visual())
        GtkLayerShell.init_for_window(self); GtkLayerShell.set_namespace(self, APP_ID); GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM); GtkLayerShell.set_exclusive_zone(self, -1); GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        for edge, on in ((GtkLayerShell.Edge.TOP, self.anchor.startswith("top")), (GtkLayerShell.Edge.BOTTOM, self.anchor.startswith("bottom")), (GtkLayerShell.Edge.LEFT, self.anchor.endswith("left")), (GtkLayerShell.Edge.RIGHT, self.anchor.endswith("right"))): GtkLayerShell.set_anchor(self, edge, on)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM, self.my); GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT, self.mx)
        self._css()
        self.card = Gtk.EventBox(); self.card.set_name("spotify-card"); self.card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK); self.card.connect("button-press-event", self._menu)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5); root.set_margin_start(16); root.set_margin_end(16); root.set_margin_top(14); root.set_margin_bottom(14); self.card.add(root)
        self.art = Gtk.Image(); self.art.set_size_request(54, 54); self.art.set_halign(Gtk.Align.START); root.pack_start(self.art, False, False, 0)
        self.title = Gtk.Label(label="SPOTIFY", xalign=0); self.title.get_style_context().add_class("title"); root.pack_start(self.title, False, False, 0)
        self.track = Gtk.Label(label="Spotify is not playing", xalign=0); self.track.get_style_context().add_class("track"); self.track.set_ellipsize(3); root.pack_start(self.track, False, False, 0)
        self.artist = Gtk.Label(label="Open Spotify to begin", xalign=0); self.artist.get_style_context().add_class("artist"); root.pack_start(self.artist, False, False, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14); controls.set_halign(Gtk.Align.CENTER); root.pack_end(controls, False, False, 0)
        for symbol, action in (("⏮", "Previous"), ("▶", "PlayPause"), ("⏭", "Next")):
            button = Gtk.Button(label=symbol); button.get_style_context().add_class("control"); button.connect("clicked", self._control, action); controls.pack_start(button, False, False, 0)
        self.add(self.card); self._apply_size(self.size_name, False); self.drag = Gtk.GestureDrag.new(self.card); self.drag.set_button(1); self.drag.connect("drag-begin", lambda *_: setattr(self, "drag_start", (self.mx, self.my))); self.drag.connect("drag-update", self._drag); self.drag.connect("drag-end", lambda *_: save({**self.config, "margin_x": self.mx, "margin_y": self.my}))
        self.proxy = None; self.art_url = None; self.refresh(); GLib.timeout_add_seconds(2, self.refresh)

    def _css(self):
        css = b'''#spotify-card { background-image: linear-gradient(145deg, rgba(38,38,38,.94), rgba(12,12,12,.92)); border: 1px solid rgba(255,255,255,.12); border-radius: 24px; box-shadow: 0 14px 32px rgba(0,0,0,.35); color: white; font-family: Inter, sans-serif; } .title { color: #1ed760; font-size: 13px; font-weight: 800; } .track { color: white; font-size: 17px; font-weight: 700; } .artist { color: rgba(255,255,255,.62); font-size: 12px; } .control { background: transparent; color: white; border: none; font-size: 20px; }'''
        provider = Gtk.CssProvider(); provider.load_from_data(css); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _proxy(self):
        try: return Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", None)
        except GLib.Error: return None

    def refresh(self):
        self.proxy = self._proxy()
        if not self.proxy:
            self.track.set_text("Spotify is not playing"); self.artist.set_text("Open Spotify to begin"); self.art.clear(); self.art_url = None; return True
        try:
            metadata = self.proxy.get_cached_property("Metadata").unpack(); title = metadata.get("xesam:title"); artist = metadata.get("xesam:artist"); art_url = metadata.get("mpris:artUrl")
            self.track.set_text(str(title.unpack() if hasattr(title, "unpack") else title or "Unknown track")); self.artist.set_text(str((artist.unpack()[0] if hasattr(artist, "unpack") and artist.unpack() else "Unknown artist")))
            art_url = art_url.unpack() if hasattr(art_url, "unpack") else art_url
            if art_url != self.art_url:
                self.art_url = art_url; self._load_art(art_url)
        except (AttributeError, GLib.Error, TypeError, KeyError): pass
        return True

    def _load_art(self, url):
        if not url:
            self.art.clear(); return
        try:
            if str(url).startswith("file://"):
                path = str(url)[7:]
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 54, 54, True)
            elif str(url).startswith("http"):
                data = urllib.request.urlopen(str(url), timeout=3).read()
                loader = GdkPixbuf.PixbufLoader(); loader.write(data); loader.close()
                pixbuf = loader.get_pixbuf().scale_simple(54, 54, GdkPixbuf.InterpType.BILINEAR)
            else:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(url), 54, 54, True)
            self.art.set_from_pixbuf(pixbuf)
        except (OSError, GLib.Error, ValueError, urllib.error.URLError):
            self.art.clear()

    def _control(self, _button, method):
        if self.proxy: self.proxy.call_sync(method, None, Gio.DBusCallFlags.NONE, 1000, None)

    def _apply_size(self, name, save_config=True):
        self.size_name = name if name in SIZES else "small"; w, h, m = SIZES[self.size_name]; self.card.set_size_request(w, h); self.resize(w, h); self.config["size"] = self.size_name
        if save_config: save(self.config)

    def _menu(self, _widget, event):
        if event.button != 3: return False
        menu = Gtk.Menu(); heading = Gtk.MenuItem(label="Widget Size"); heading.set_sensitive(False); menu.append(heading); first = None
        for name, label in (("small", "Small"), ("medium", "Medium"), ("large", "Large")):
            item = Gtk.RadioMenuItem.new_with_label(None, label) if first is None else Gtk.RadioMenuItem.new_with_label_from_widget(first, label)
            if first is None: first = item
            item.set_active(name == self.size_name); item.connect("toggled", lambda i, n: i.get_active() and self._apply_size(n), name); menu.append(item)
        menu.append(Gtk.SeparatorMenuItem()); exit_item = Gtk.MenuItem(label="Exit Widget"); exit_item.connect("activate", lambda _i: self.destroy()); menu.append(exit_item); menu.show_all(); menu.popup_at_pointer(event); return True

    def _drag(self, _gesture, dx, dy):
        horizontal = 1 if self.anchor.endswith("left") else -1
        vertical = 1 if self.anchor.startswith("top") else -1
        self.mx = max(0, self.drag_start[0] + horizontal * dx)
        self.my = max(0, self.drag_start[1] + vertical * dy)
        self.mx = round(self.mx / SNAP_GRID) * SNAP_GRID
        self.my = round(self.my / SNAP_GRID) * SNAP_GRID
        side = GtkLayerShell.Edge.LEFT if self.anchor.endswith("left") else GtkLayerShell.Edge.RIGHT
        edge = GtkLayerShell.Edge.TOP if self.anchor.startswith("top") else GtkLayerShell.Edge.BOTTOM
        GtkLayerShell.set_margin(self, side, int(self.mx)); GtkLayerShell.set_margin(self, edge, int(self.my))

if __name__ == "__main__":
    win = SpotifyWidget(); win.connect("destroy", Gtk.main_quit); win.show_all(); Gtk.main()
