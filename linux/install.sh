#!/usr/bin/env bash
# Установка Glyphstroke для Linux: зависимости, права, автозапуск.
# Запускать из каталога с исходниками:  ./install.sh
set -euo pipefail

PREFIX=/opt/glyphstroke
BIN=/usr/local/bin
SRC="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

RUNTIME_DIR="/run/user/$(id -u "$USER_NAME" 2>/dev/null || echo 0)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
as_user() { sudo -u "$USER_NAME" env HOME="$USER_HOME" XDG_RUNTIME_DIR="$RUNTIME_DIR" "$@"; }

if [ "$(id -u)" -ne 0 ]; then
    say "Нужны права root — перезапускаю через sudo"
    exec sudo -E "$0" "$@"
fi

# Раньше программа называлась strokeit. Две версии не могут работать разом:
# мышь захватывается эксклюзивно, второй демон её просто не получит.
LEGACY_EXT="$USER_HOME/.local/share/gnome-shell/extensions/strokeit@strokeit.local"
if [ -d /opt/strokeit ] || [ -x /usr/local/bin/strokeit ] || [ -d "$LEGACY_EXT" ]; then
    say "0/5 Убираю прежнюю версию (strokeit)"
    as_user systemctl --user disable --now strokeit 2>/dev/null || true
    as_user gnome-extensions disable strokeit@strokeit.local 2>/dev/null || true
    rm -rf /opt/strokeit /usr/local/bin/strokeit /usr/local/bin/strokeitd \
           /etc/udev/rules.d/99-strokeit.rules /etc/modules-load.d/strokeit.conf \
           /usr/share/applications/strokeit.desktop "$LEGACY_EXT"
    rm -f "$USER_HOME/.config/systemd/user/strokeit.service"
    rm -f "$USER_HOME/.config/systemd/user/graphical-session.target.wants/strokeit.service"
    echo "прежняя версия убрана; ваши жесты и настройки останутся в"
    echo "$USER_HOME/.config/strokeit и будут перенесены при первом запуске"
fi

say "1/5 Зависимости"
# Обязательные — без них не работает демон; остальные нужны только редактору.
REQUIRED_PKGS=(python3-evdev python3-yaml)
OPTIONAL_PKGS=(python3-gi gir1.2-gtk-3.0 python3-gi-cairo)

installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "ok installed"; }

missing=()
for pkg in "${REQUIRED_PKGS[@]}" "${OPTIONAL_PKGS[@]}"; do
    installed "$pkg" || missing+=("$pkg")
done

if [ ${#missing[@]} -eq 0 ]; then
    echo "всё нужное уже стоит"
else
    echo "не хватает: ${missing[*]}"
    # На снятых с поддержки выпусках Ubuntu зеркала отдают 404 и update падает.
    # Это не повод останавливаться: ставим из тех индексов, что уже есть.
    apt-get update -qq || echo "внимание: apt update отработал с ошибками, "\
        "пробуем поставить из имеющихся индексов"
    apt-get install -y "${missing[@]}" || echo "внимание: apt install не осилил часть пакетов"
fi

# Проверяем не пакеты, а то, что действительно нужно, — импорты.
if ! python3 -c "import evdev, yaml" 2>/dev/null; then
    cat <<TEXT

Не хватает обязательных модулей: evdev и PyYAML.

Похоже, apt до них не добрался. Если ваш выпуск Ubuntu снят с поддержки,
его зеркала пусты — тогда быстрее всего поставить модули помимо apt:

    sudo apt-get install -y python3-pip
    sudo pip3 install --break-system-packages evdev PyYAML
    sudo ./install.sh

Либо привести источники в порядок и повторить установку. Архив снятых с
поддержки выпусков — old-releases.ubuntu.com; адреса лежат в
/etc/apt/sources.list.d/ubuntu.sources (новый формат) или в
/etc/apt/sources.list. Проверить: sudo apt-get update

Радикальный вариант — обновиться до поддерживаемого выпуска:
    sudo do-release-upgrade

TEXT
    exit 1
fi

if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "внимание: GTK 3 недоступен — жесты работать будут, редактор «glyphstroke gui» нет"
    echo "          поставить позже: sudo apt-get install python3-gi gir1.2-gtk-3.0 python3-gi-cairo"
fi

say "2/5 Код в $PREFIX"
install -d "$PREFIX"
rm -rf "$PREFIX/glyphstroke"
cp -r "$SRC/glyphstroke" "$PREFIX/glyphstroke"
cat > "$BIN/glyphstroke" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH=/opt/glyphstroke python3 -m glyphstroke.cli "$@"
WRAP
cat > "$BIN/glyphstroked" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH=/opt/glyphstroke python3 -m glyphstroke.daemon "$@"
WRAP
chmod +x "$BIN/glyphstroke" "$BIN/glyphstroked"
install -Dm644 "$SRC/glyphstroke/data/glyphstroke.desktop" \
    /usr/share/applications/glyphstroke.desktop

# значок программы: растр по размерам, вектор и одноцветный для панели
for size in 16 24 32 48 64 128 256; do
    install -Dm644 "$SRC/glyphstroke/data/icons/$size/glyphstroke.png" \
        "/usr/share/icons/hicolor/${size}x${size}/apps/glyphstroke.png"
done
install -Dm644 "$SRC/glyphstroke/data/icons/glyphstroke.svg" \
    /usr/share/icons/hicolor/scalable/apps/glyphstroke.svg
install -Dm644 "$SRC/glyphstroke/data/icons/glyphstroke-symbolic.svg" \
    /usr/share/icons/hicolor/symbolic/apps/glyphstroke-symbolic.svg
# без обновления кэша темы значок не появится до перезахода
gtk-update-icon-cache -qtf /usr/share/icons/hicolor 2>/dev/null || true

say "3/5 Права на устройства ввода"
install -Dm644 "$SRC/glyphstroke/data/99-glyphstroke.rules" /etc/udev/rules.d/99-glyphstroke.rules
udevadm control --reload-rules || true
udevadm trigger --subsystem-match=misc --attr-match=name=uinput || true
modprobe uinput || true
echo uinput > /etc/modules-load.d/glyphstroke.conf
usermod -aG input "$USER_NAME"
echo "пользователь $USER_NAME добавлен в группу input"

say "4/5 Настройки пользователя"
sudo -u "$USER_NAME" env HOME="$USER_HOME" PYTHONPATH="$PREFIX" \
    python3 -m glyphstroke.cli init

# В GNOME след за курсором рисует расширение оболочки: обычному приложению
# в Wayland не дают ни позиции курсора, ни слоя поверх окон. Дальше за копией
# следит сам демон — при запуске он сверяет версии и обновляет её; здесь мы
# просто не ждём первого запуска.
if command -v gnome-shell >/dev/null 2>&1; then
    sudo -u "$USER_NAME" env HOME="$USER_HOME" PYTHONPATH="$PREFIX" \
        python3 -m glyphstroke.cli shell-extension install || true
fi

say "5/5 Автозапуск"
# Если служба уже включена, это переустановка поверх — подхватываем новый код.
# Если нет, включаем сами: просить об этом человека отдельной командой незачем,
# без автозапуска жесты перестанут работать после первой же перезагрузки.
if as_user systemctl --user is-enabled glyphstroke >/dev/null 2>&1; then
    if as_user systemctl --user restart glyphstroke; then
        echo "служба перезапущена с обновлённой версией"
    else
        echo "внимание: перезапустить службу не вышло — сделайте вручную:"
        echo "  systemctl --user restart glyphstroke"
    fi
else
    if as_user env PYTHONPATH="$PREFIX" python3 -m glyphstroke.cli service enable; then
        echo "автозапуск включён"
    else
        echo "внимание: включить автозапуск не вышло — сделайте после перезахода:"
        echo "  glyphstroke service enable"
    fi
fi

cat <<TEXT

Осталось одно: выйдите из системы и войдите снова. Группа input подхватывается
только при входе, а расширение оболочки, которое рисует след и мишень, GNOME
загружает только при старте сеанса. Обойти это нельзя.

Полезное:
  glyphstroke doctor      проверить права и найденные мыши
  glyphstroke bind        слушать только одну мышь
  glyphstroke pause       временно отпустить мышь (resume — вернуть)
  glyphstroke export ФАЙЛ выгрузить жесты, import ФАЙЛ — загрузить
  glyphstroke shell-extension status   след за курсором в GNOME
  glyphstroke gui         редактор жестов
  glyphstroke test        показывать распознанное, ничего не выполняя
  glyphstroke list        какие жесты сейчас настроены

TEXT
