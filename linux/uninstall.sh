#!/usr/bin/env bash
# Полное удаление Glyphstroke. Настройки в ~/.config/glyphstroke не трогаются.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -E "$0" "$@"
fi
USER_NAME="${SUDO_USER:-root}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_ID="$(id -u "$USER_NAME")"

sudo -u "$USER_NAME" env HOME="$USER_HOME" XDG_RUNTIME_DIR="/run/user/$USER_ID" \
    systemctl --user disable --now glyphstroke 2>/dev/null || true

rm -rf /opt/glyphstroke /usr/local/bin/glyphstroke /usr/local/bin/glyphstroked \
       /etc/udev/rules.d/99-glyphstroke.rules /etc/modules-load.d/glyphstroke.conf \
       /usr/share/applications/glyphstroke.desktop
rm -f "$USER_HOME/.config/systemd/user/glyphstroke.service"
for size in 16 24 32 48 64 128 256; do
    rm -f "/usr/share/icons/hicolor/${size}x${size}/apps/glyphstroke.png"
done
rm -f /usr/share/icons/hicolor/scalable/apps/glyphstroke.svg \
      /usr/share/icons/hicolor/symbolic/apps/glyphstroke-symbolic.svg
gtk-update-icon-cache -qtf /usr/share/icons/hicolor 2>/dev/null || true
udevadm control --reload-rules || true

echo "удалено; настройки остались в $USER_HOME/.config/glyphstroke"
echo "группа input у пользователя $USER_NAME оставлена — снимите вручную:"
echo "  sudo gpasswd -d $USER_NAME input"
