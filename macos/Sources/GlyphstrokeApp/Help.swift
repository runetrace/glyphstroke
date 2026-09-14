import Foundation

/// Содержимое окна справки. Темы берутся по языку интерфейса.
///
/// Текст короткий и под мак: без консольных команд, привычными словами. По
/// смыслу совпадает с версиями для Linux и Windows, но не дословно — там свои
/// реалии (evdev, расширение оболочки, область уведомлений), здесь свои
/// (Универсальный доступ, строка меню, клавиша ⌘).
enum Help {
    struct Topic: Identifiable {
        let title: String
        let body: String
        var id: String { title }
    }

    static func topics() -> [Topic] { L.language == "ru" ? russian : english }

    private static let russian: [Topic] = [
        Topic(title: "Как это работает", body: """
        Зажмите правую кнопку мыши, проведите знак, отпустите — выполнится \
        привязанное действие. Пока кнопка зажата, её нажатие придерживается: \
        если вы просто щёлкнули, не рисуя, программа досылает обычный щелчок, \
        и контекстное меню открывается как всегда.

        Значок программы живёт в строке меню, вверху справа. Оттуда — жесты, \
        настройки, пауза и журнал.
        """),
        Topic(title: "Первый жест", body: """
        Откройте «Жесты…» в меню значка. Нажмите «Добавить» — появится новый \
        жест. Задайте название, а фигуру — двумя способами: кодом направлений \
        (например, «D-R» — вниз, потом вправо) или нарисуйте образец на холсте. \
        Чем больше образцов, тем терпимее распознавание.

        На вкладке «Действия» выберите, что жест делает: например, стандартное \
        действие «Назад» или сочетание клавиш. Правки сохраняются сами.
        """),
        Topic(title: "Из чего состоит жест", body: """
        Фигура — код направлений и нарисованные образцы. Действия — что \
        выполнить. «Где работает» — в каких программах жест включён (пусто — \
        везде). Допуск поворота — насколько криво можно рисовать.

        Кнопка-мишень в «Где работает» подставит программу под курсором: \
        нажмите её и щёлкните по нужному окну.
        """),
        Topic(title: "Действия", body: """
        Стандартное действие выбирается из списка (копировать, вставить, \
        свернуть окно и так далее) и переносится между системами как есть: в \
        файле лежит имя, а сочетание клавиш подставляет та система, где жест \
        сработал. Клавиши пишутся через плюс: cmd+shift+t, ctrl+Left, F5.

        Ещё бывают: ввод текста, запуск программы, команда оболочки, действие \
        над окном, щелчок, прокрутка, пауза. Действия выполняются по порядку \
        сверху вниз.
        """),
        Topic(title: "Меню под жестом", body: """
        У жеста может быть меню: на вкладке «Меню» добавьте пункты, у каждого — \
        название и свои действия. Тогда при срабатывании жест вместо своих \
        действий откроет меню у курсора.

        Выберите пункт щелчком или стрелками. Меню закрывается по Esc, щелчку \
        мимо и само по времени — оно не может остаться висеть на экране.
        """),
        Topic(title: "Наборы жестов", body: """
        Набор — это отдельная папка жестов. Слева вверху в редакторе выберите \
        набор или заведите новый кнопкой «+»: новый набор создаётся копией \
        текущего, чтобы не начинать с пустого места.

        Основной набор лежит в «gestures», остальные — в «profiles» рядом. \
        Раскладка общая с версиями для Linux и Windows, поэтому папку настроек \
        можно переносить между машинами целиком.
        """),
        Topic(title: "Тема и язык", body: """
        В настройках выбираются тема (системная, светлая, тёмная) и язык \
        (системный, русский, английский). Оба применяются сразу, во всех \
        открытых окнах, без перезапуска.
        """),
        Topic(title: "Если что-то не работает", body: """
        Проверьте разрешения: программе нужен Универсальный доступ, иначе \
        система не отдаст ей события мыши и заголовки окон. Пункт «Выдать \
        разрешения…» в меню значка открывает нужный раздел настроек.

        Если жест не срабатывает — откройте «Журнал…» и нарисуйте его ещё раз. \
        В журнале видно, что распознано, с какой уверенностью и какой жест был \
        ближе всех. Две одинаковые фигуры у разных жестов не сработают никогда: \
        распознаватель отказывается выбирать между равными, и редактор \
        предупреждает об этом оранжевой строкой.
        """),
    ]

    private static let english: [Topic] = [
        Topic(title: "How it works", body: """
        Hold the right mouse button, draw a sign, release — the assigned action \
        runs. While the button is held, its click is held back too: if you just \
        clicked without drawing, the program sends the plain click through, and \
        the context menu opens as always.

        The program lives in the menu bar, top right. Gestures, settings, pause \
        and the log are all there.
        """),
        Topic(title: "Your first gesture", body: """
        Open “Gestures…” from the menu bar icon and press “Add”. Give the \
        gesture a name, then set its shape one of two ways: by a direction code \
        (“D-R” means down, then right) or by drawing a sample on the canvas. \
        The more samples, the more forgiving the recognition.

        On the “Actions” tab choose what the gesture does — a standard action \
        such as “Back”, or a key combination. Edits save themselves.
        """),
        Topic(title: "What a gesture is made of", body: """
        The shape is a direction code and the samples you drew. The actions are \
        what to run. “Where it works” lists the apps the gesture is enabled in \
        (empty means everywhere). Rotation tolerance is how crooked your drawing \
        may be.

        The target button in “Where it works” fills in the app under the \
        cursor: press it, then click the window you mean.
        """),
        Topic(title: "Actions", body: """
        A standard action is picked from a list (copy, paste, minimize and so \
        on) and travels between systems as is: the file keeps the name, and \
        whichever system runs the gesture supplies the keys. Keys are written \
        with pluses: cmd+shift+t, ctrl+Left, F5.

        There are also: typing text, launching an app, a shell command, a window \
        action, a click, scrolling and a pause. Actions run top to bottom.
        """),
        Topic(title: "A menu under a gesture", body: """
        A gesture can carry a menu: add items on the “Menu” tab, each with its \
        own name and actions. The gesture then opens a menu at the cursor \
        instead of running its own actions.

        Pick an item by clicking or with the arrow keys. The menu closes on Esc, \
        on a click outside, and on its own after a timeout — it cannot be left \
        hanging on screen.
        """),
        Topic(title: "Gesture sets", body: """
        A set is a separate folder of gestures. Pick one at the top left of the \
        editor, or start a new one with “+”: a new set is created as a copy of \
        the current one, so you never begin from nothing.

        The main set lives in “gestures”, the others in “profiles” next to it. \
        The layout is shared with the Linux and Windows versions, so the whole \
        settings folder can be carried between machines.
        """),
        Topic(title: "Theme and language", body: """
        Settings hold the theme (system, light, dark) and the language (system, \
        Russian, English). Both apply at once, in every open window, without a \
        restart.
        """),
        Topic(title: "When something does not work", body: """
        Check the permissions: the program needs Accessibility, otherwise the \
        system hands it neither mouse events nor window titles. “Grant \
        permissions…” in the menu bar opens the right pane of System Settings.

        If a gesture does not fire, open “Log…” and draw it again. The log shows \
        what was recognised, how confidently, and which gesture came closest. \
        Two gestures with the same shape will never fire: the recogniser refuses \
        to choose between equals, and the editor warns about it with an orange \
        line.
        """),
    ]
}
