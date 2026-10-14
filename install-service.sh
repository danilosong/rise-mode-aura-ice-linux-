#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UNIT_DIR=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user
UNIT_FILE="$UNIT_DIR/rise-mode-temp.service"

mkdir -p "$UNIT_DIR"
sed "s|@PROJECT_DIR@|$PROJECT_DIR|g" "$PROJECT_DIR/rise-mode-temp.service.in" > "$UNIT_FILE"
systemctl --user daemon-reload
systemctl --user enable --now rise-mode-temp.service

printf '%s\n' 'Serviço instalado e iniciado; ele iniciará automaticamente nos próximos logins.'
printf '%s\n' 'Estado:  systemctl --user status rise-mode-temp.service'
printf '%s\n' 'Logs:    journalctl --user -u rise-mode-temp.service -f'
