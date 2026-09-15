using System.Collections.Generic;

namespace Glyphstroke.App;

/// <summary>Содержимое окна справки. Темы берутся по языку интерфейса.</summary>
/// <remarks>
/// Текст короткий и под Windows: без консольных команд, привычными словами.
/// Формат общий с версией для Linux по смыслу, но не дословно — там свои реалии
/// (evdev, расширение оболочки), здесь свои.
/// </remarks>
internal static class Help
{
    public readonly record struct Topic(string Title, string Body);

    public static IReadOnlyList<Topic> Topics() => L.Language == "ru" ? Russian : English;

    private static readonly List<Topic> Russian = new()
    {
        new("Как это работает",
            "Зажмите правую кнопку мыши, проведите знак, отпустите — выполнится привязанное " +
            "действие. Пока кнопка зажата, её нажатие придерживается: если вы просто щёлкнули, " +
            "не рисуя, программа досылает обычный щелчок, и контекстное меню открывается как всегда.\n\n" +
            "Значок программы живёт в области уведомлений, справа внизу. Оттуда — жесты, настройки, " +
            "пауза и журнал."),
        new("Первый жест",
            "Откройте «Жесты…» в меню значка. Нажмите «Добавить» — появится новый жест. Задайте " +
            "название, а фигуру — двумя способами: кодом направлений (например, «D-R» — вниз, потом " +
            "вправо) или нарисуйте образец на холсте. Чем больше образцов, тем терпимее распознавание.\n\n" +
            "На вкладке «Действия» выберите, что жест делает: например, стандартное действие " +
            "«Назад» или сочетание клавиш. Правки сохраняются сами."),
        new("Из чего состоит жест",
            "Фигура — код направлений и/или нарисованные образцы. Действия — что выполнить. " +
            "«Где работает» — в каких программах жест включён (пусто — везде). Допуск поворота — " +
            "насколько криво можно рисовать.\n\n" +
            "Кнопка «🎯 Выбрать окно» в «Где работает» добавит программу: нажмите её и " +
            "перетащите на нужное окно — в список попадёт строка вида «class:программа.exe»."),
        new("Действия",
            "Стандартное действие выбирается из списка (копировать, вставить, свернуть окно и так " +
            "далее) и переносится между системами как есть. Клавиши пишутся через плюс: ctrl+shift+t, " +
            "alt+Left, F5. Ещё бывают: ввод текста, запуск программы, команда, действие над окном, " +
            "щелчок, прокрутка, пауза. Действия выполняются по порядку сверху вниз."),
        new("Меню под жестом",
            "У жеста может быть меню: на вкладке «Меню» добавьте пункты, у каждого — название и свои " +
            "действия. Тогда при срабатывании жест вместо своих действий откроет меню у курсора. " +
            "Выберите пункт щелчком — выполнятся его действия. Меню закрывается по Esc, щелчку мимо " +
            "или само, если долго ничего не выбирать.\n\n" +
            "Так одной фигурой можно заменить десяток жестов: один росчерк — меню, а в нём выбор."),
        new("Наборы жестов",
            "Слева над списком — выбор набора. «Основной» и заведённые вами наборы; кнопки + и – " +
            "заводят и удаляют. Новый набор копирует текущий, чтобы не начинать с нуля. Переключение " +
            "сразу меняет действующие жесты. Наборы переносятся между системами."),
        new("Тема и язык",
            "В настройках, раздел «Оформление»: тема окон (как в системе / светлая / тёмная) меняется " +
            "сразу, язык интерфейса — при следующем запуске."),
        new("Если что-то не работает",
            "Жест не срабатывает — посмотрите журнал (в меню значка): там видно, что распозналось и " +
            "какой ближайший жест. Возможно, фигура слишком похожа на другую — увеличьте различие " +
            "или уменьшите допуск поворота.\n\n" +
            "В отдельных программах, запущенных от администратора, перехват мыши может не доходить — " +
            "это ограничение Windows."),
    };

    private static readonly List<Topic> English = new()
    {
        new("How it works",
            "Hold the right mouse button, draw a sign, release — the bound action runs. While the " +
            "button is held, its press is kept back: if you just click without drawing, the program " +
            "sends the usual click and the context menu opens as always.\n\n" +
            "The icon lives in the notification area, bottom right — gestures, settings, pause and the " +
            "log are there."),
        new("Your first gesture",
            "Open \"Gestures…\" from the icon menu. Press \"Add\" — a new gesture appears. Give it a " +
            "name and a shape in one of two ways: a direction code (for example \"D-R\" — down, then " +
            "right) or draw a sample on the canvas. The more samples, the more forgiving the matching.\n\n" +
            "On the \"Actions\" tab choose what the gesture does: a standard action like \"Back\" or a " +
            "key combination. Changes save themselves."),
        new("What a gesture is made of",
            "The shape — a direction code and/or drawn samples. Actions — what to run. \"Where it " +
            "works\" — which programs the gesture is on in (empty means everywhere). Rotation " +
            "tolerance — how crooked you may draw.\n\n" +
            "The target button in \"Where it works\" fills in the program under the cursor: press it " +
            "and drag onto the window you want."),
        new("Actions",
            "A standard action is chosen from a list (copy, paste, minimise the window and so on) and " +
            "moves between systems as is. Keys are written with a plus: ctrl+shift+t, alt+Left, F5. " +
            "There are also: typing text, launching a program, a command, a window action, a click, " +
            "scrolling, a delay. Actions run top to bottom."),
        new("A menu under a gesture",
            "A gesture can have a menu: on the \"Menu\" tab add items, each with a name and its own " +
            "actions. Then, when it fires, the gesture opens a menu at the cursor instead of running " +
            "its own actions. Pick an item with a click — its actions run. The menu closes on Escape, " +
            "a click away, or by itself after a while.\n\n" +
            "This way one shape replaces a dozen gestures: one stroke opens a menu, the choice is inside."),
        new("Gesture sets",
            "Above the list on the left — the set picker. \"Main\" and the sets you create; the + and – " +
            "buttons add and remove them. A new set copies the current one so you do not start from " +
            "scratch. Switching changes the active gestures at once. Sets move between systems."),
        new("Theme and language",
            "In settings, the \"Appearance\" section: the window theme (as in the system / light / dark) " +
            "changes at once, the interface language on the next launch."),
        new("When something does not work",
            "A gesture does not fire — look at the log (in the icon menu): it shows what was recognised " +
            "and the closest gesture. The shape may be too close to another one — make them more " +
            "distinct or lower the rotation tolerance.\n\n" +
            "In some programs run as administrator the mouse hook may not reach — that is a Windows " +
            "limitation."),
    };
}
