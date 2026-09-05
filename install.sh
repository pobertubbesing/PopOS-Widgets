#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${HOME}/.local/share"
CONFIG_DIR="${HOME}/.config"
SYSTEMD_DIR="${CONFIG_DIR}/systemd/user"

if ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("GtkLayerShell", "0.1")' 2>/dev/null; then
  echo "Missing GTK/GtkLayerShell dependencies."
  echo "Install them on Pop!_OS with:"
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1"
  exit 1
fi

install -Dm755 "${REPO_DIR}/widgets/weather/weather_widget.py" "${DATA_DIR}/cosmic-weather-widget/weather_widget.py"
install -Dm755 "${REPO_DIR}/widgets/calendar/calendar_widget.py" "${DATA_DIR}/cosmic-calendar-widget/calendar_widget.py"
install -Dm755 "${REPO_DIR}/widgets/system/system_widget.py" "${DATA_DIR}/cosmic-system-widget/system_widget.py"
while IFS= read -r icon; do
  install -Dm644 "$icon" "${DATA_DIR}/cosmic-weather-widget/icons/$(basename "$icon")"
done < <(find "${REPO_DIR}/widgets/weather/icons" -maxdepth 1 -type f -name '*.svg')
install -Dm644 "${REPO_DIR}/systemd/cosmic-weather-widget.service" "${SYSTEMD_DIR}/cosmic-weather-widget.service"
install -Dm644 "${REPO_DIR}/systemd/cosmic-calendar-widget.service" "${SYSTEMD_DIR}/cosmic-calendar-widget.service"
install -Dm644 "${REPO_DIR}/systemd/cosmic-system-widget.service" "${SYSTEMD_DIR}/cosmic-system-widget.service"
install -Dm755 "${REPO_DIR}/bin/widget" "${HOME}/.local/bin/widget"

if [[ ! -e "${CONFIG_DIR}/cosmic-weather-widget/config.json" ]]; then
  install -Dm644 "${REPO_DIR}/config/weather.json" "${CONFIG_DIR}/cosmic-weather-widget/config.json"
fi
if [[ ! -e "${CONFIG_DIR}/cosmic-calendar-widget/config.json" ]]; then
  install -Dm644 "${REPO_DIR}/config/calendar.json" "${CONFIG_DIR}/cosmic-calendar-widget/config.json"
fi
if [[ ! -e "${CONFIG_DIR}/cosmic-system-widget/config.json" ]]; then
  install -Dm644 "${REPO_DIR}/config/system.json" "${CONFIG_DIR}/cosmic-system-widget/config.json"
fi

systemctl --user daemon-reload
systemctl --user enable --now cosmic-weather-widget.service cosmic-calendar-widget.service cosmic-system-widget.service

echo "Weather and Calendar widgets installed and running."
echo "Run 'widget' to check status or start a stopped widget."
