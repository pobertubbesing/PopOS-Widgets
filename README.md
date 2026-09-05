# Pop!_OS Widgets

Desktop widgets for Pop!_OS with COSMIC: translucent weather, calendar, and system monitor widgets, plus the `widget` terminal command.

## Install

On a Pop!_OS device with Python GTK and GTK Layer Shell available:

```bash
git clone https://github.com/pobertubbesing/PopOS-Widgets.git
cd PopOS-Widgets
./install.sh
```

If dependencies are missing, install them with:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1
```

The installer places the widgets in your user profile, installs their systemd user services, and starts all three widgets. Existing settings are preserved.

## Use

Right-click a widget to change its size, edit weather settings, or exit it. Run `widget` in a terminal to see each widget's status and start one that is stopped.
