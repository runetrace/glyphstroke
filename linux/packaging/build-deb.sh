#!/usr/bin/env bash
# Сборка .deb для Glyphstroke. Ничего, кроме dpkg-deb, не требуется:
# пакет собирается из готового дерева, без debhelper и правил debian/rules.
#
#   ./packaging/build-deb.sh            собрать в ./dist
#   ./packaging/build-deb.sh /tmp/out   собрать в другой каталог
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$SRC/dist}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/glyphstroke/version.py")"
[ -n "$VERSION" ] || { echo "не нашёл версию в glyphstroke/version.py" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/glyphstroke"

# --- сам код: в /usr/lib/glyphstroke, как обычная поставка вне dist-packages ---
install -d "$PKG/usr/lib/glyphstroke"
cp -r "$SRC/glyphstroke" "$PKG/usr/lib/glyphstroke/glyphstroke"
find "$PKG/usr/lib/glyphstroke" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$PKG/usr/lib/glyphstroke" -name '*.pyc' -delete

# --- команды ---
install -d "$PKG/usr/bin"
cat > "$PKG/usr/bin/glyphstroke" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH=/usr/lib/glyphstroke python3 -m glyphstroke.cli "$@"
WRAP
cat > "$PKG/usr/bin/glyphstroked" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH=/usr/lib/glyphstroke python3 -m glyphstroke.daemon "$@"
WRAP
chmod 755 "$PKG/usr/bin/glyphstroke" "$PKG/usr/bin/glyphstroked"

# --- ярлык и значки ---
install -Dm644 "$SRC/glyphstroke/data/glyphstroke.desktop" \
    "$PKG/usr/share/applications/glyphstroke.desktop"
for size in "$SRC"/glyphstroke/data/icons/[0-9]*; do
    name="$(basename "$size")"
    install -Dm644 "$size/glyphstroke.png" \
        "$PKG/usr/share/icons/hicolor/${name}x${name}/apps/glyphstroke.png"
done
install -Dm644 "$SRC/glyphstroke/data/icons/glyphstroke.svg" \
    "$PKG/usr/share/icons/hicolor/scalable/apps/glyphstroke.svg"
install -Dm644 "$SRC/glyphstroke/data/icons/glyphstroke-symbolic.svg" \
    "$PKG/usr/share/icons/hicolor/symbolic/apps/glyphstroke-symbolic.svg"

# --- расширение GNOME Shell (системное, видно всем уже при старте сеанса) ---
# Кладём в /usr/share, а не в дом пользователя: тогда оболочка сканирует его при
# входе, и демон включает его на ходу, без «двойного перезахода». Демон копию в
# ~/.local в этом случае не делает (см. shellext.ensure_current).
EXT_UUID="glyphstroke@glyphstroke.local"
install -d "$PKG/usr/share/gnome-shell/extensions/$EXT_UUID"
cp -r "$SRC/glyphstroke/data/gnome-extension/$EXT_UUID/." \
    "$PKG/usr/share/gnome-shell/extensions/$EXT_UUID/"
find "$PKG/usr/share/gnome-shell/extensions/$EXT_UUID" -type f -exec chmod 644 {} +

# --- служба systemd (общий для всех пользователей user-юнит) ---
# Ставим готовый юнит с явным ExecStart в /usr/lib/systemd/user, чтобы включать
# автозапуск глобально (systemctl --global enable) — без сеанса пользователя.
install -d "$PKG/usr/lib/systemd/user"
sed 's#@EXEC@#/usr/bin/glyphstroked#' "$SRC/glyphstroke/data/glyphstroke.service" \
    > "$PKG/usr/lib/systemd/user/glyphstroke.service"
chmod 644 "$PKG/usr/lib/systemd/user/glyphstroke.service"

# --- права на устройства ввода ---
install -Dm644 "$SRC/glyphstroke/data/99-glyphstroke.rules" \
    "$PKG/usr/lib/udev/rules.d/99-glyphstroke.rules"
install -d "$PKG/usr/lib/modules-load.d"
echo uinput > "$PKG/usr/lib/modules-load.d/glyphstroke.conf"
chmod 644 "$PKG/usr/lib/modules-load.d/glyphstroke.conf"

# --- документация ---
install -Dm644 "$SRC/README.md" "$PKG/usr/share/doc/glyphstroke/README.md"
install -Dm644 "$SRC/README.ru.md" "$PKG/usr/share/doc/glyphstroke/README.ru.md"
install -Dm644 "$SRC/../LICENSE" "$PKG/usr/share/doc/glyphstroke/copyright"

# --- описание пакета ---
install -d "$PKG/DEBIAN"
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: glyphstroke
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: runetrace <runetrace@proton.me>
Depends: python3 (>= 3.9), python3-evdev, python3-yaml
Recommends: python3-gi, gir1.2-gtk-3.0, python3-gi-cairo
Description: control the computer with gestures
 Hold the right button, draw a sign, release it — the bound action runs.
 The plain right click keeps working and no context menu flashes.
 .
 The capture works at the kernel level through evdev and uinput, so it
 behaves the same in X11 and in Wayland. A GNOME Shell extension from the
 package draws the trail and the gesture menu where Wayland gives an
 ordinary application neither the pointer position nor a layer above the
 windows.
CONTROL

cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    python3 -m compileall -q /usr/lib/glyphstroke >/dev/null 2>&1 || true
    udevadm control --reload-rules >/dev/null 2>&1 || true
    udevadm trigger --subsystem-match=misc --attr-match=name=uinput >/dev/null 2>&1 || true
    modprobe uinput >/dev/null 2>&1 || true
    gtk-update-icon-cache -qtf /usr/share/icons/hicolor >/dev/null 2>&1 || true
    update-desktop-database >/dev/null 2>&1 || true

    # Автозапуск включаем ГЛОБАЛЬНО — для всех пользователей сразу. Так надёжно:
    # не нужен ни живой сеанс пользователя, ни его шина, ни угадывание HOME.
    # Прежний путь (systemctl --user из-под root через runuser) на чистой
    # установке молча не срабатывал и служба оставалась выключенной.
    timeout 10 systemctl --global enable glyphstroke.service >/dev/null 2>&1 || true

    USER_NAME="${SUDO_USER:-}"
    if [ -n "$USER_NAME" ]; then
        USER_UID="$(id -u "$USER_NAME" 2>/dev/null || true)"
        USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

        # Доступ к устройствам ввода
        if ! id -nG "$USER_NAME" 2>/dev/null | tr ' ' '\n' | grep -qx input; then
            usermod -aG input "$USER_NAME" >/dev/null 2>&1 || true
        fi

        # Запустить сразу, если сеанс жив (иначе поднимется при следующем входе).
        # HOME задаём явно: runuser -u его не ставит. Это необязательный довесок
        # к глобальному автозапуску, поэтому уводим в отвязанный фон (setsid …&):
        # если systemctl --user зависнет, окно графического .deb-установщика не
        # должно висеть вместе с ним, ожидая завершения postinst.
        if [ -n "$USER_UID" ] && [ -n "$USER_HOME" ] && [ -d "/run/user/$USER_UID" ]; then
            AS_USER="runuser -u $USER_NAME -- env HOME=$USER_HOME XDG_RUNTIME_DIR=/run/user/$USER_UID DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$USER_UID/bus"
            setsid sh -c "
                timeout 15 $AS_USER env PYTHONPATH=/usr/lib/glyphstroke python3 -m glyphstroke.cli init >/dev/null 2>&1
                timeout 10 $AS_USER systemctl --user daemon-reload >/dev/null 2>&1
                timeout 10 $AS_USER systemctl --user restart glyphstroke >/dev/null 2>&1
            " >/dev/null 2>&1 </dev/null &
        fi
    fi

    if [ -n "$2" ]; then
        # при обновлении $2 — прежняя версия, при первой установке пусто
        cat <<TEXT

Glyphstroke обновлён с версии $2.

  Служба перезапущена, расширение оболочки демон обновил сам. В GNOME
  оболочка загружает расширения только при старте сеанса, поэтому
  перезайдите в систему — иначе продолжит работать прежняя версия.

  Проверить: glyphstroke doctor

TEXT
    else
    cat <<TEXT

Glyphstroke установлен. Доступ к мыши выдан, расширение оболочки поставит сам
демон при первом запуске.

  Остался один шаг: выйдите из системы и войдите снова. Группа input
  подхватывается только при входе, а расширения оболочка загружает только
  при старте сеанса — обойти это нельзя.

TEXT
    echo "  Автозапуск включён — служба поднимется при входе в систему."
    cat <<TEXT

  Дальше: glyphstroke doctor — проверит права и найденные мыши,
  glyphstroke gui — редактор жестов.

TEXT
    fi
fi
exit 0
POST

cat > "$PKG/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e

# кэш байткода создал postinst, dpkg о нём не знает и каталог не уберёт
find /usr/lib/glyphstroke -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find /usr/lib/glyphstroke -depth -type d -empty -delete 2>/dev/null || true
udevadm control --reload-rules >/dev/null 2>&1 || true
gtk-update-icon-cache -qtf /usr/share/icons/hicolor >/dev/null 2>&1 || true

# Глобальный автозапуск снимаем при удалении, но не при обновлении
# (при upgrade postrm зовётся с "upgrade" — тогда трогать не надо).
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    timeout 10 systemctl --global disable glyphstroke.service >/dev/null 2>&1 || true
fi

if [ "$1" = "purge" ]; then
    echo "Настройки остались в ~/.config/glyphstroke — удалите их сами, если не нужны."
fi
exit 0
POSTRM
cat > "$PKG/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e

# Перед удалением (не перед обновлением) прибираем за собой в живых сеансах:
# останавливаем демон, выключаем расширение (иначе панельный значок висит,
# пока оболочка держит его загруженным) и убираем пользовательскую копию.
# Всё это — в отвязанном фоне (setsid …&): вызовы в чужой сеанс могут зависнуть
# на D-Bus, а окно графического установщика не должно висеть вместе с ними,
# ожидая завершения prerm. Каждый вызов вдобавок под timeout.
if [ "$1" = "remove" ]; then
    setsid sh -c '
        for rt in /run/user/*; do
            [ -d "$rt" ] || continue
            uid="${rt##*/}"
            case "$uid" in ""|*[!0-9]*) continue ;; esac
            [ "$uid" -ge 1000 ] 2>/dev/null || continue
            uname="$(getent passwd "$uid" | cut -d: -f1)"
            [ -n "$uname" ] || continue
            uhome="$(getent passwd "$uid" | cut -d: -f6)"
            as="runuser -u $uname -- env HOME=$uhome XDG_RUNTIME_DIR=$rt DBUS_SESSION_BUS_ADDRESS=unix:path=$rt/bus"
            timeout 5 $as gnome-extensions disable glyphstroke@glyphstroke.local >/dev/null 2>&1 || true
            timeout 5 $as systemctl --user stop glyphstroke >/dev/null 2>&1 || true
            rm -rf "$uhome/.local/share/gnome-shell/extensions/glyphstroke@glyphstroke.local" 2>/dev/null || true
        done
    ' >/dev/null 2>&1 </dev/null &
fi
exit 0
PRERM

chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm" "$PKG/DEBIAN/prerm"

mkdir -p "$OUT"
DEB="$OUT/glyphstroke_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$PKG" "$DEB" >/dev/null
echo "$DEB"
