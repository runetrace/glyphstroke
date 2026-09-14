import Foundation

/// Перевод строк интерфейса.
///
/// Устроено как в версии для Linux: ключ — это русский исходный текст, а
/// каталог даёт английский перевод. По умолчанию программа говорит по-английски;
/// русский включается настройкой `language` (auto / en / ru). При `auto` язык
/// берётся из системы.
///
/// Строки с подстановками не кладём в каталог целиком: переводим отдельно
/// статичную часть, а значение приклеиваем снаружи. Так один ключ обслуживает
/// любые числа и имена.
enum L {
    /// Текущий язык интерфейса: "en" или "ru".
    static var language = "en"

    /// Задать язык из настройки. "auto" — по системной локали.
    static func use(_ setting: String) {
        switch setting {
        case "ru": language = "ru"
        case "en": language = "en"
        default:
            let code = Locale.preferredLanguages.first ?? "en"
            language = code.hasPrefix("ru") ? "ru" : "en"
        }
    }

    /// Перевод: по-русски возвращаем сам ключ, иначе английский из каталога.
    static func tr(_ key: String) -> String {
        language == "ru" ? key : (english[key] ?? key)
    }

    /// Ключи — русский текст, значения — английский. Только видимый интерфейс.
    static let english: [String: String] = [
        // окна
        "Glyphstroke — жесты": "Glyphstroke — Gestures",
        "Glyphstroke — настройки": "Glyphstroke — Settings",
        "Glyphstroke — журнал": "Glyphstroke — Log",
        // меню в строке меню
        "Пауза": "Pause",
        "Продолжить": "Resume",
        "Жесты…": "Gestures…",
        "Настройки…": "Settings…",
        "Перечитать жесты": "Reload gestures",
        "Журнал…": "Log…",
        "Проверить обновления…": "Check for updates…",
        "О программе…": "About…",
        "Выдать разрешения…": "Grant permissions…",
        "Выйти": "Quit",
        "Нет разрешений": "No permissions",
        "На паузе": "Paused",
        "Перехват не включён": "Capture is off",
        "Жестов загружено:": "Gestures loaded:",
        // о программе / обновления
        "Управление устройством жестами\n\n": "Control your computer with mouse gestures\n\n",
        "Вопросы и сообщения об ошибках: runetrace@proton.me":
            "Questions and bug reports: runetrace@proton.me",
        "Вышла версия": "Version is out:",
        "Установлена последняя версия": "The latest version is installed:",
        "Новых выпусков нет — или сервер не ответил.":
            "No newer releases — or the server did not answer.",
        "Обновление ставится вручную: программа не заменяет себя сама.":
            "The update is installed manually: the program does not replace itself.",
        "Установлена": "Installed:",
        "Открыть страницу загрузки": "Open the download page",
        "Позже": "Later",
        "Понятно": "OK",
        // разрешения / первый запуск
        "Glyphstroke установлен": "Glyphstroke is installed",
        "Осталось выдать два разрешения — иначе система не пустит программу к мыши.":
            "Two permissions are left to grant — otherwise the system will not let the program near the mouse.",
        "Мониторинг ввода": "Input Monitoring",
        "Универсальный доступ": "Accessibility",
        "Разрешает видеть движения мыши. Без него жесты не рисуются вовсе.":
            "Allows seeing mouse movement. Without it gestures are not drawn at all.",
        "Разрешает выполнять действия жеста и узнавать, какое окно впереди.":
            "Allows running gesture actions and knowing the active window.",
        "Всё выдано. Можно рисовать: зажмите правую кнопку и проведите мышью.":
            "All granted. You can draw: hold the right button and move the mouse.",
        "В «Системных настройках» найдите Glyphstroke в списке и включите переключатель. ":
            "In System Settings find Glyphstroke in the list and turn on the switch. ",
        "Если программы в списке нет, нажмите кнопку выше — она добавит её.":
            "If the program is not in the list, press the button above — it adds it.",
        "После выдачи разрешений программу нужно перезапустить.":
            "After granting the permissions the program must be restarted.",
        "Перезапустить": "Restart",
        "Закрыть": "Close",
        "Открыть…": "Open…",
        "Выдать…": "Grant…",
        "Проверить заново": "Check again",
        "Разрешения": "Permissions",
        // редактор
        "Добавить": "Add",
        "Удалить": "Delete",
        "Дублировать": "Duplicate",
        "Выберите жест слева или добавьте новый": "Select a gesture on the left or add a new one",
        "Жест": "Gesture",
        "Название": "Name",
        "Описание": "Description",
        "Включён": "Enabled",
        "Фигура": "Shape",
        "Направления": "Directions",
        "например: D-R": "for example: D-R",
        "Буквы направлений через дефис: R вправо, L влево, U вверх, D вниз, ":
            "Direction letters with a dash: R right, L left, U up, D down, ",
        "DR вниз-вправо и так далее. Несколько вариантов — через запятую.":
            "DR down-right and so on. Several options — comma-separated.",
        "Образцы росчерка": "Stroke samples",
        "Нарисуйте здесь фигуру жеста": "Draw the gesture shape here",
        "Добавить образец": "Add a sample",
        "Убрать все образцы": "Remove all samples",
        "Действия": "Actions",
        "Добавить действие": "Add an action",
        "Где работает": "Where it works",
        "Только в программах": "Only in programs",
        "Тонкости": "Fine points",
        "Допуск поворота": "Rotation tolerance",
        "Насколько криво можно рисовать. Больше 45° делать не стоит: ":
            "How crooked you may draw. More than 45° is not worth it: ",
        "жест начнёт путаться со своим же поворотом.":
            "the gesture starts to be confused with its own rotation.",
        "Новый жест": "New gesture",
        // типы действий
        "Стандартное действие": "Standard action",
        "Клавиши": "Keys",
        "Ввести текст": "Type text",
        "Команда": "Command",
        "Запуск программы": "Launch a program",
        "Окно": "Window",
        "Кнопка мыши": "Mouse button",
        "Прокрутка": "Scroll",
        "Пауза, мс": "Delay, ms",
        "Ничего": "Nothing",
        // настройки
        "Мышь": "Mouse",
        "Кнопка-модификатор": "Modifier button",
        "Правая": "Right",
        "Средняя": "Middle",
        "Короткое движение — это щелчок": "A short move is a click",
        "Неопознанный росчерк": "An unrecognised stroke",
        "отдать программе": "give to the program",
        "проглотить": "swallow",
        "След": "Trail",
        "Рисовать след": "Draw the trail",
        "Цвет": "Colour",
        "Непрозрачность": "Opacity",
        "Гаснет за": "Fades in",
        "Запуск": "Startup",
        "Запускать при входе в систему": "Launch at login",
        "Программа живёт в строке меню и без окна: без автозапуска ":
            "The program lives in the menu bar without a window: without autostart ",
        "жесты перестанут работать после перезагрузки.":
            "gestures stop working after a reboot.",
        "Обновления": "Updates",
        "Проверять обновления": "Check for updates",
        "Раз в сутки программа спрашивает страницу выпусков, не вышла ли ":
            "Once a day the program asks the releases page whether a newer ",
        "версия новее. Сама она не обновляется: перехват мыши — не то место, ":
            "version is out. It does not update itself: mouse capture is not the place ",
        "где уместна тихая подмена. Проверка обращается к чужому серверу и ":
            "for a silent swap. The check contacts a third-party server and ",
        "ничего о вашей системе не сообщает.": "reports nothing about your system.",
        "Где лежат выпуски": "Where the releases are",
        "Файлы": "Files",
        "Настройки и жесты": "Settings and gestures",
        "Показать в Finder": "Show in Finder",
        "Применить": "Apply",
        "Язык": "Language",
        "как в системе": "as in the system",
        "Оформление": "Appearance",
        "Тема": "Theme",
        "светлая": "light",
        "тёмная": "dark",
        "Язык интерфейса сменится при следующем запуске.":
            "The interface language changes on the next launch.",
        // пояснения в настройках
        "«Отдать программе» значит, что после неудачного росчерка откроется ":
            "\"Give to the program\" means that after a failed stroke ",
        "обычное контекстное меню. Так понятнее: человек видит, что жест не вышел.":
            "the usual context menu opens. It is clearer: you see the gesture did not work.",
        "Пусто — жест работает везде. По строке на программу: ":
            "Empty — the gesture works everywhere. One line per program: ",
        "«class:com.apple.Safari» — точное совпадение, иначе строка понимается ":
            "\"class:com.apple.Safari\" is an exact match, otherwise the line is read ",
        "как выражение и ищется в «программа | заголовок окна». Имя программы ":
            "as an expression matched against \"program | window title\". The program name ",
        "видно в журнале, когда жест срабатывает.": "is shown in the log when a gesture fires.",
        "Стандартное действие выбирается из списка и переносится между ":
            "A standard action is chosen from a list and moves between ",
        "системами как есть. Клавиши пишутся через плюс: cmd+shift+t, ":
            "systems as is. Keys are written with a plus: cmd+shift+t, ",
        "ctrl+Left, F5. Действия выполняются по порядку сверху вниз.":
            "ctrl+Left, F5. Actions run top to bottom.",
        "Та же фигура у:": "The same shape is on:",
        "Пока фигуры совпадают, не сработает ни один из жестов.":
            "While the shapes match, none of the gestures will fire.",
        // подсказки полей действий
        "cmd+t": "cmd+t",
        "текст, который напечатать": "the text to type",
        "команда оболочки": "a shell command",
        "Safari или com.apple.Safari": "Safari or com.apple.Safari",
        "minimize, close, fullscreen, activate": "minimize, close, fullscreen, activate",
        "left, right, middle": "left, right, middle",
        "up 3": "up 3",
        "200": "200",
        // прочее
        "выкл": "off",
        "фигура не задана": "no shape set",
        "образцов:": "samples:",
        "только:": "only:",
        "Код:": "Code:",
        "Толщина:": "Width:",
        // добор
        "Очистить": "Clear",
        "Образцы": "Samples",
        "Жесты": "Gestures",
        "Программы": "Programs",
        "Текст": "Text",
        "Программа": "Program",
        "Щелчок": "Click",
        "Настройки": "Settings",
        "видеть движения мыши": "to see mouse movement",
        "выполнять действия и знать активное окно": "run actions and know the active window",
        "После выдачи разрешения программу нужно перезапустить: ":
            "After granting the permission the program must be restarted: ",
        "запущенной система продолжает отдавать прежний ответ.":
            "the system keeps giving a running program the old answer.",
        "Так бывает, если программа запущена не из папки «Программы».":
            "This happens if the program was launched not from the Applications folder.",
        "Не удалось сохранить": "Could not save",
        "Не удалось сохранить настройки:": "Could not save the settings:",
        "Автозапуск не изменился:": "Autostart did not change:",
        "пикс.": "px",
        "мс": "ms",
    ]
}

/// Короткий помощник, чтобы в коде было `tr("…")`.
func tr(_ key: String) -> String { L.tr(key) }
