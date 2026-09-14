#!/usr/bin/env bash
# Сборка дистрибутива: один файл Glyphstroke-<версия>.dmg.
#
# Внутри образа — программа и ярлык папки «Программы». Установка выглядит так,
# как на маке принято: открыть образ, перетащить значок вправо. Ни терминала,
# ни установщика с шагами «Далее» человеку не нужно.
#
#   ./scripts/make-dmg.sh
#   SIGN_ID="Developer ID Application: Имя (TEAMID)" ./scripts/make-dmg.sh
#       собрать подписанным — без этого другой компьютер откажется запускать
#       программу, сославшись на неизвестного разработчика
#
# Дальше, если раздавать: заверить образ у Apple (нотаризация). Команды —
# в конце вывода.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$SRC/dist}"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SRC/Resources/Info.plist")"
DMG="$OUT/Glyphstroke-$VERSION.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/3 Программа"
"$SRC/scripts/build-app.sh" "$OUT" >/dev/null
cp -R "$OUT/Glyphstroke.app" "$STAGE/Glyphstroke.app"
ln -s /Applications "$STAGE/Программы"

# Короткая записка внутри образа: что делать после перетаскивания. Разрешения
# всё равно придётся выдать руками, и лучше человек прочтёт об этом заранее,
# чем решит, что программа сломана.
cat > "$STAGE/Прочитайте меня.txt" <<'TEXT'
Glyphstroke — управление устройством жестами.

Установка:
  1. Перетащите Glyphstroke в папку «Программы» (ярлык рядом).
  2. Запустите Glyphstroke из «Программ».
  3. Программа откроет окно и попросит два разрешения — «Мониторинг ввода»
     и «Универсальный доступ». Их выдаёт только человек, в «Системных
     настройках»; в окне есть кнопки, которые открывают нужную страницу.
  4. После выдачи нажмите «Перезапустить» в том же окне: система отдаёт
     свежие разрешения только новому запуску программы.

Дальше значок появится в строке меню справа вверху. Там же — список жестов,
настройки и журнал.

Как пользоваться: зажать правую кнопку мыши, нарисовать знак, отпустить.
Обычный щелчок правой кнопкой работает как работал.
TEXT

say "2/3 Образ"
mkdir -p "$OUT"
rm -f "$DMG"
hdiutil create -volname "Glyphstroke" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

if [ -n "${SIGN_ID:-}" ]; then
    codesign --force --sign "$SIGN_ID" "$DMG"
fi

say "3/3 Готово"
echo "$DMG"

if [ -z "${SIGN_ID:-}" ]; then
cat <<'TEXT'

Образ собран без подписи разработчика. На вашей машине он откроется, на чужой
macOS скажет «программу невозможно проверить». Для раздачи нужна учётная запись
Apple Developer и два шага:

  SIGN_ID="Developer ID Application: Имя (TEAMID)" ./scripts/make-dmg.sh
  xcrun notarytool submit dist/Glyphstroke-<версия>.dmg --keychain-profile glyphstroke --wait
  xcrun stapler staple dist/Glyphstroke-<версия>.dmg

Профиль ключей заводится один раз:
  xcrun notarytool store-credentials glyphstroke --apple-id ПОЧТА \
      --team-id TEAMID --password ПАРОЛЬ-ПРИЛОЖЕНИЯ
TEXT
fi
