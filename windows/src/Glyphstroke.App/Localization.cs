using System.Collections.Generic;
using System.Globalization;

namespace Glyphstroke.App;

/// <summary>Перевод строк интерфейса.</summary>
/// <remarks>
/// Устроено как в версиях для Linux и macOS: ключ — это русский исходный текст,
/// а каталог даёт английский перевод. По умолчанию программа говорит
/// по-английски; русский включается настройкой <c>language</c> (auto / en / ru).
/// При <c>auto</c> язык берётся из системы.
///
/// Строки с подстановками не кладём в каталог целиком: переводим отдельно
/// статичную часть, а значение приклеиваем снаружи.
/// </remarks>
internal static class L
{
    public static string Language = "en";

    public static void Use(string setting)
    {
        Language = setting switch
        {
            "ru" => "ru",
            "en" => "en",
            _ => CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "ru" ? "ru" : "en",
        };
    }

    /// <summary>Перевод: по-русски возвращаем сам ключ, иначе английский.</summary>
    public static string Tr(string key) =>
        Language == "ru" ? key : (English.TryGetValue(key, out var value) ? value : key);

    private static readonly Dictionary<string, string> English = new()
    {
        // окна
        ["Glyphstroke — жесты"] = "Glyphstroke — Gestures",
        ["Glyphstroke — настройки"] = "Glyphstroke — Settings",
        // трей и общие
        ["Glyphstroke уже работает — значок в области уведомлений, справа внизу."] =
            "Glyphstroke is already running — the icon is in the notification area, bottom right.",
        ["Пауза"] = "Pause",
        ["Продолжить"] = "Resume",
        ["Жесты…"] = "Gestures…",
        ["Настройки…"] = "Settings…",
        ["Перечитать жесты"] = "Reload gestures",
        ["Журнал…"] = "Log…",
        ["Проверить обновления…"] = "Check for updates…",
        ["О программе…"] = "About…",
        ["Справка…"] = "Help…",
        ["Glyphstroke — справка"] = "Glyphstroke — Help",
        ["Выйти"] = "Quit",
        ["На паузе"] = "Paused",
        ["Перехват не включён"] = "Capture is off",
        ["Жестов загружено:"] = "Gestures loaded:",
        // о программе / обновления
        ["Управление устройством жестами.\n\n"] = "Control your computer with mouse gestures.\n\n",
        ["Вопросы и сообщения об ошибках: runetrace@proton.me"] =
            "Questions and bug reports: runetrace@proton.me",
        ["О программе"] = "About",
        ["Обновление"] = "Update",
        ["Обновления"] = "Updates",
        ["Обновление ставится вручную: программа не заменяет себя сама."] =
            "The update is installed manually: the program does not replace itself.",
        ["\n\nОткрыть страницу загрузки?"] = "\n\nOpen the download page?",
        ["Новых выпусков нет — или сервер не ответил."] =
            "No newer releases — or the server did not answer.",
        // ошибки/диалоги
        ["Не удалось включить перехват мыши:\n\n"] = "Could not enable mouse capture:\n\n",
        ["Не удалось поставить перехват мыши: "] = "Could not install the mouse hook: ",
        ["Не удалось сохранить жест:\n\n"] = "Could not save the gesture:\n\n",
        ["Не удалось сохранить настройки:\n\n"] = "Could not save the settings:\n\n",
        ["не вижу активного окна"] = "no active window is visible",
        ["glyphstroke-журнал.txt"] = "glyphstroke-log.txt",
        // редактор
        ["Добавить"] = "Add",
        ["Основной"] = "Main",
        ["Новый набор жестов"] = "New gesture set",
        ["Удалить набор"] = "Delete the set",
        ["Название набора"] = "Set name",
        ["ОК"] = "OK",
        ["Отмена"] = "Cancel",
        ["Дублировать"] = "Duplicate",
        ["Удалить"] = "Delete",
        ["Без названия"] = "Untitled",
        ["Название"] = "Name",
        ["Пояснение"] = "Description",
        ["Включён"] = "Enabled",
        ["Направления"] = "Directions",
        ["Буквы направлений через дефис: R вправо, L влево, U вверх, D вниз, "] =
            "Direction letters with a dash: R right, L left, U up, D down, ",
        ["DR вниз-вправо и так далее. Несколько вариантов — через запятую."] =
            "DR down-right and so on. Several options — comma-separated.",
        ["Жест"] = "Gesture",
        ["Где работает"] = "Where it works",
        ["Образцы росчерка"] = "Stroke samples",
        ["Нарисуйте здесь фигуру жеста"] = "Draw the gesture shape here",
        ["Добавить образец"] = "Add a sample",
        ["Убрать все образцы"] = "Remove all samples",
        ["Действия"] = "Actions",
        ["Меню"] = "Menu",
        ["Росчерк"] = "Stroke",
        ["Пункт"] = "Item",
        ["Название пункта"] = "Item name",
        ["Добавить пункт"] = "Add an item",
        ["Убрать пункт"] = "Remove the item",
        ["Если есть пункты, жест открывает меню у курсора: выбери пункт — "] =
            "With items, the gesture opens a menu at the cursor: pick an item — ",
        ["выполнятся его действия. Без пунктов жест просто делает свои действия."] =
            "its actions run. Without items the gesture just runs its own actions.",
        ["Добавить действие"] = "Add an action",
        ["Выбрать окно…"] = "Pick a window…",
        ["Нажмите и перетащите на нужное окно"] =
            "Press and drag onto the target window",
        ["Только в программах"] = "Only in programs",
        ["Пусто — жест работает везде. По строке на программу: «class:chrome.exe» — "] =
            "Empty — the gesture works everywhere. One line per program: \"class:chrome.exe\" — ",
        ["точное совпадение, иначе строка понимается как выражение и ищется "] =
            "an exact match, otherwise the line is read as an expression matched ",
        ["в «программа | заголовок окна»."] = "against \"program | window title\".",
        ["Допуск поворота"] = "Rotation tolerance",
        ["Пока фигуры совпадают, не сработает ни один из жестов."] =
            "While the shapes match, none of the gestures will fire.",
        ["Новый жест"] = "New gesture",
        // типы действий
        ["Стандартное действие"] = "Standard action",
        ["Клавиши"] = "Keys",
        ["Ввести текст"] = "Type text",
        ["Команда"] = "Command",
        ["Запуск программы"] = "Launch a program",
        ["Окно"] = "Window",
        ["Кнопка мыши"] = "Mouse button",
        ["Прокрутка"] = "Scroll",
        ["Пауза, мс"] = "Delay, ms",
        ["Ничего"] = "Nothing",
        // настройки
        ["Мышь"] = "Mouse",
        ["Кнопка-модификатор"] = "Modifier button",
        ["Правая кнопка"] = "Right button",
        ["Средняя кнопка"] = "Middle button",
        ["Короткое движение — щелчок"] = "A short move is a click",
        ["Если жест не распознан"] = "If a gesture is not recognised",
        ["отдать программе"] = "give to the program",
        ["проглотить"] = "swallow",
        ["«Отдать программе» значит, что после неудачного росчерка откроется "] =
            "\"Give to the program\" means that after a failed stroke ",
        ["обычное контекстное меню. Так понятнее: видно, что жест не вышел."] =
            "the usual context menu opens. It is clearer: you see the gesture did not work.",
        ["Не мешать в программах"] = "Do not interfere in programs",
        ["По строке на программу: «class:game.exe» — точное совпадение, "] =
            "One line per program: \"class:game.exe\" is an exact match, ",
        ["иначе строка понимается как выражение."] = "otherwise the line is read as an expression.",
        ["Отключаться в полноэкранных"] = "Turn off in fullscreen",
        ["След"] = "Trail",
        ["Рисовать след"] = "Draw the trail",
        ["Цвет"] = "Colour",
        ["Толщина"] = "Width",
        ["Непрозрачность, %"] = "Opacity, %",
        ["Гаснет за, мс"] = "Fades in, ms",
        ["Запуск и обновления"] = "Startup and updates",
        ["Запускать при входе в систему"] = "Launch at login",
        ["Проверять обновления"] = "Check for updates",
        ["Где лежат выпуски"] = "Where the releases are",
        ["Раз в сутки программа спрашивает страницу выпусков, не вышла ли "] =
            "Once a day the program asks the releases page whether a newer ",
        ["версия новее. Сама она не обновляется: перехват мыши — не то место, "] =
            "version is out. It does not update itself: mouse capture is not the place ",
        ["где уместна тихая подмена."] = "for a silent swap.",
        ["Файлы"] = "Files",
        ["Программы"] = "Programs",
        ["Открыть папку настроек"] = "Open the settings folder",
        ["Применить"] = "Apply",
        ["Закрыть"] = "Close",
        // язык
        ["Язык"] = "Language",
        ["как в системе"] = "as in the system",
        ["Оформление"] = "Appearance",
        ["Тема"] = "Theme",
        ["светлая"] = "light",
        ["тёмная"] = "dark",
        ["Тема и язык применятся при следующем запуске."] =
            "The theme and language apply on the next launch.",
        ["Язык интерфейса сменится при следующем запуске."] =
            "The interface language changes on the next launch.",
        // подписи с подстановкой (статичная часть)
        ["точек"] = "points",
        ["  (выкл)"] = "  (off)",
        ["образцов:"] = "samples:",
        ["код нарисованного:"] = "drawn code:",
        ["фигура не задана"] = "no shape set",
        ["Вышла версия"] = "Version is out:",
        ["установлена"] = "installed:",
        ["Установлена последняя версия"] = "The latest version is installed:",
        ["Та же фигура у:"] = "The same shape is on:",
        ["Удалить жест"] = "Delete the gesture",
        // «Где работает», список программ, настройки ползунков
        ["px"] = "px",
        ["мс"] = "ms",
        ["Новый"] = "New",
        ["Порог щелчка"] = "Click threshold",
        ["Гаснет за"] = "Fades in",
        ["Непрозрачность"] = "Opacity",
        ["Убрать программу"] = "Remove program",
        ["Не мешать в программах:"] = "Don't interfere in programs:",
        ["Пусто — жест работает во всех программах."] = "Empty — the gesture works in all programs.",
        ["Пусто — жесты работают во всех программах."] = "Empty — gestures work in all programs.",
        ["Наведите мишень на окно программы, где жесты мешают. "] =
            "Point the target at the window of a program where gestures get in the way. ",
        ["Строки можно снимать крестиком."] = "Rows can be removed with the ✕.",
        ["Движение короче порога — это обычный щелчок, он уходит программе. "] =
            "A movement shorter than the threshold is a normal click and goes to the program. ",
        ["Так жест не срабатывает от случайного клика."] =
            "This keeps a gesture from firing on an accidental click.",
        ["Если протянуть мышь короче этого расстояния, это считается обычным щелчком и передаётся программе — жест не запускается. Больше значение — реже случайные срабатывания."] =
            "If you drag the mouse less than this distance, it counts as a normal click and goes to the program — no gesture runs. Larger value means fewer accidental triggers.",
        ["Насколько сильно рисунок может быть повёрнут и всё равно распознаться. 0° — строго как образец; больше — терпимее к наклону руки."] =
            "How much the drawing may be rotated and still be recognized. 0° — exactly like the sample; higher — more tolerant of a tilted hand.",
    };
}
