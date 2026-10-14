#!/bin/sh
set -eu

UNIT_FILE=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user/rise-mode-temp.service
systemctl --user disable --now rise-mode-temp.service || true
rm -f "$UNIT_FILE"
systemctl --user daemon-reload
printf '%s\n' 'Serviço removido do início automático.'
