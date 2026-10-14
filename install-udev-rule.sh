#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RULE_FILE=/etc/udev/rules.d/99-rise-mode-hid.rules

sudo install -m 0644 "$PROJECT_DIR/99-rise-mode-hid.rules" "$RULE_FILE"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
systemctl --user restart rise-mode-temp.service 2>/dev/null || true

printf '%s\n' 'Regra HID instalada. O serviço de telemetria foi reiniciado.'
printf '%s\n' 'Confira: systemctl --user status rise-mode-temp.service'
