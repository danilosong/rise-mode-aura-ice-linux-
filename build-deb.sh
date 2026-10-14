#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERSION=${1:-1.0.0}
PACKAGE=rise-mode-aura-ice-linux
BUILD_DIR=$(mktemp -d)
PACKAGE_ROOT="$BUILD_DIR/$PACKAGE"
OUTPUT_DIR="$PROJECT_DIR/dist"

case "$VERSION" in
  *[!0-9A-Za-z.+:~_-]*|'')
    printf '%s\n' 'Versão inválida.' >&2
    exit 2
    ;;
esac

trap 'rm -rf "$BUILD_DIR"' EXIT HUP INT TERM
mkdir -p "$PACKAGE_ROOT/DEBIAN" \
  "$PACKAGE_ROOT/usr/lib/rise-mode-aura-ice-linux/static" \
  "$PACKAGE_ROOT/usr/lib/systemd/user" \
  "$PACKAGE_ROOT/usr/lib/udev/rules.d" \
  "$PACKAGE_ROOT/usr/bin" \
  "$OUTPUT_DIR"

install -m 0644 "$PROJECT_DIR/app.py" "$PACKAGE_ROOT/usr/lib/rise-mode-aura-ice-linux/app.py"
install -m 0644 "$PROJECT_DIR/static/index.html" "$PACKAGE_ROOT/usr/lib/rise-mode-aura-ice-linux/static/index.html"
install -m 0644 "$PROJECT_DIR/99-rise-mode-hid.rules" "$PACKAGE_ROOT/usr/lib/udev/rules.d/99-rise-mode-hid.rules"

sed 's|@PROJECT_DIR@|/usr/lib/rise-mode-aura-ice-linux|g' \
  "$PROJECT_DIR/rise-mode-temp.service.in" \
  > "$PACKAGE_ROOT/usr/lib/systemd/user/rise-mode-temp.service"
chmod 0644 "$PACKAGE_ROOT/usr/lib/systemd/user/rise-mode-temp.service"

cat > "$PACKAGE_ROOT/usr/bin/rise-mode-temp" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/rise-mode-aura-ice-linux/app.py "$@"
EOF

cat > "$PACKAGE_ROOT/usr/bin/rise-mode-temp-setup" <<'EOF'
#!/bin/sh
set -eu
if [ "$(id -u)" -eq 0 ]; then
  printf '%s\n' 'Execute este comando sem sudo, na sessão do usuário que usará o visor.' >&2
  exit 1
fi
systemctl --user daemon-reload
systemctl --user enable --now rise-mode-temp.service
printf '%s\n' 'Serviço instalado e ativado para iniciar ao entrar na sessão.'
printf '%s\n' 'Confira com: systemctl --user status rise-mode-temp.service'
EOF

cat > "$PACKAGE_ROOT/usr/bin/rise-mode-temp-remove" <<'EOF'
#!/bin/sh
set -eu
if [ "$(id -u)" -eq 0 ]; then
  printf '%s\n' 'Execute este comando sem sudo, na sessão do usuário.' >&2
  exit 1
fi
systemctl --user disable --now rise-mode-temp.service || true
systemctl --user daemon-reload
printf '%s\n' 'Serviço desativado para este usuário.'
EOF

chmod 0755 "$PACKAGE_ROOT/usr/bin/rise-mode-temp" \
  "$PACKAGE_ROOT/usr/bin/rise-mode-temp-setup" \
  "$PACKAGE_ROOT/usr/bin/rise-mode-temp-remove"
find "$PACKAGE_ROOT" -type d -exec chmod 0755 {} +

cat > "$PACKAGE_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Danilo Song <danilosong@outlook.com>
Depends: python3 (>= 3.10), systemd, udev
Description: Rise Mode water cooler CPU temperature display for Ubuntu
 Sends CPU temperature to the USB HID display in the Rise Mode water cooler.
 Includes a local monitoring dashboard and a per-user systemd service.
EOF

cat > "$PACKAGE_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=hidraw || true
  fi
fi
exit 0
EOF
chmod 0755 "$PACKAGE_ROOT/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" \
  "$OUTPUT_DIR/${PACKAGE}_${VERSION}_all.deb"
printf 'Pacote criado: %s\n' "$OUTPUT_DIR/${PACKAGE}_${VERSION}_all.deb"
