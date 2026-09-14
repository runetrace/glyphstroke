#!/usr/bin/env bash
# Сборка Glyphstroke.app из пакета SwiftPM.
#
# Xcode-проекта в репозитории нет намеренно: .xcodeproj — это большой
# машинно-порождаемый файл, который конфликтует при каждом слиянии, а всё, что
# от него нужно, делают четыре команды ниже. Открыть проект в Xcode это не
# мешает: File → Open → Package.swift.
#
#   ./scripts/build-app.sh                 собрать в ./dist/Glyphstroke.app
#   ./scripts/build-app.sh /tmp/out        собрать в другой каталог
#   SIGN_ID="Developer ID Application: Имя (TEAMID)" ./scripts/build-app.sh
#       собрать и подписать; без подписи система при первом запуске будет
#       ругаться, и открывать придётся через правый клик → «Открыть»
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$SRC/dist}"
APP="$OUT/Glyphstroke.app"
CONFIG="${CONFIG:-release}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/4 Сборка"
cd "$SRC"
swift build -c "$CONFIG"
BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"

say "2/4 Каркас .app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN_DIR/glyphstroke" "$APP/Contents/MacOS/GlyphstrokeApp"
cp "$SRC/Resources/Info.plist" "$APP/Contents/Info.plist"
cp "$SRC/Resources/Glyphstroke.icns" "$APP/Contents/Resources/Glyphstroke.icns"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# Ресурсы SwiftPM (стартовые жесты) лежат отдельным пакетом рядом с
# исполняемым файлом. Bundle.module ищет его в том числе в Contents/Resources,
# поэтому просто кладём туда целиком.
for bundle in "$BIN_DIR"/*.bundle; do
    [ -e "$bundle" ] || continue
    cp -R "$bundle" "$APP/Contents/Resources/"
done

say "3/4 Подпись"
if [ -n "${SIGN_ID:-}" ]; then
    # --options runtime обязателен: без защищённой среды выполнения
    # нотаризация не принимает приложение.
    codesign --force --deep --options runtime --timestamp \
        --sign "$SIGN_ID" "$APP"
    codesign --verify --strict --verbose=2 "$APP"
else
    # Подпись «ad hoc» нужна и без учётной записи разработчика: неподписанный
    # двоичный файл macOS не пустит дальше первого запуска вовсе.
    codesign --force --deep --sign - "$APP"
    echo "подписано временно (ad hoc): раздавать такое нельзя, для себя сойдёт"
fi

say "4/4 Готово"
echo "$APP"
cat <<'TEXT'

Дальше:
  open dist/Glyphstroke.app         запустить
  При первом запуске система попросит два разрешения — «Мониторинг ввода» и
  «Универсальный доступ». После выдачи программу надо перезапустить: запущенной
  программе система продолжает отдавать прежний ответ.

Для раздачи другим (нужна учётная запись Apple Developer):
  SIGN_ID="Developer ID Application: Имя (TEAMID)" ./scripts/build-app.sh
  ditto -c -k --keepParent dist/Glyphstroke.app dist/Glyphstroke.zip
  xcrun notarytool submit dist/Glyphstroke.zip --keychain-profile glyphstroke --wait
  xcrun stapler staple dist/Glyphstroke.app
TEXT
