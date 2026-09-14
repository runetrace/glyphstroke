import SwiftUI
import GlyphstrokeCore


/// Редактор жестов: слева список, справа подробности.
///
/// Правки сохраняются сами, через полсекунды после последнего нажатия клавиши.
/// Кнопки «Сохранить» здесь нет намеренно: жест — это не документ, человек
/// приходит сюда поменять одну строчку, и забытая кнопка означала бы потерянную
/// правку и полчаса разбирательств, почему мышь делает старое.
struct EditorView: View {
    @ObservedObject var model: AppModel

    @State private var newProfileName = ""
    @State private var askingProfileName = false
    @State private var confirmingProfileRemoval = false

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selectedID) {
                ForEach(model.gestures) { gesture in
                    GestureRow(gesture: gesture)
                        .tag(gesture.id)
                        .contextMenu {
                            Button(tr("Дублировать")) { model.duplicate(gesture) }
                            Button(tr("Удалить"), role: .destructive) { model.delete(gesture) }
                        }
                }
            }
            .frame(minWidth: 240)
            .safeAreaInset(edge: .top) {
                ProfileBar(model: model,
                           askingName: $askingProfileName,
                           confirmingRemoval: $confirmingProfileRemoval)
            }
            .alert(tr("Новый набор жестов"), isPresented: $askingProfileName) {
                TextField(tr("Название набора"), text: $newProfileName)
                Button(tr("Отмена"), role: .cancel) { newProfileName = "" }
                Button(tr("Завести")) {
                    let name = newProfileName.trimmingCharacters(in: .whitespaces)
                    newProfileName = ""
                    guard !name.isEmpty else { return }
                    model.addProfile(named: name)
                }
            }
            .alert(tr("Удалить набор?"), isPresented: $confirmingProfileRemoval) {
                Button(tr("Отмена"), role: .cancel) {}
                Button(tr("Удалить"), role: .destructive) { model.removeActiveProfile() }
            } message: {
                Text(tr("Жесты этого набора удалятся вместе с ним. Основной набор не тронется."))
            }
            .safeAreaInset(edge: .bottom) {
                HStack {
                    Button {
                        model.addGesture()
                    } label: {
                        Label(tr("Добавить"), systemImage: "plus")
                    }
                    Spacer()
                    Button {
                        if let selected = model.selected { model.delete(selected) }
                    } label: {
                        Label(tr("Удалить"), systemImage: "minus")
                    }
                    .disabled(model.selected == nil)
                }
                .buttonStyle(.borderless)
                .padding(8)
            }
        } detail: {
            if let gesture = model.selected {
                GestureDetailView(model: model, gesture: gesture)
                    .id(gesture.id)
            } else {
                ContentUnavailableLikeView()
            }
        }
        .navigationTitle(tr("Жесты"))
        .safeAreaInset(edge: .top) {
            if let problem = model.problem {
                Text(problem)
                    .font(.callout)
                    .foregroundStyle(.white)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.red.opacity(0.85))
            }
        }
    }
}

/// Строка списка: имя, фигура и пометка «выключен».
private struct GestureRow: View {
    let gesture: Gesture

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(gesture.name)
                    .foregroundStyle(gesture.enabled ? .primary : .secondary)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if !gesture.enabled {
                Text(tr("выкл"))
                    .font(.caption2)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.secondary.opacity(0.2), in: Capsule())
            }
        }
        .padding(.vertical, 2)
    }

    private var subtitle: String {
        var parts: [String] = []
        if !gesture.directions.isEmpty { parts.append(gesture.directions.joined(separator: ", ")) }
        if !gesture.templates.isEmpty { parts.append("\(tr("образцов:")) \(gesture.templates.count)") }
        if !gesture.event.isEmpty { parts.append(gesture.event) }
        if !gesture.apps.isEmpty { parts.append("\(tr("только:")) \(gesture.apps.joined(separator: ", "))") }
        return parts.isEmpty ? tr("фигура не задана") : parts.joined(separator: " · ")
    }
}

/// Заглушка пустого выбора. Своя, а не ContentUnavailableView: тот появился
/// только в macOS 14, а программа работает начиная с 13-й.
private struct ContentUnavailableLikeView: View {
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "scribble.variable")
                .font(.system(size: 40))
                .foregroundStyle(.secondary)
            Text(tr("Выберите жест слева или добавьте новый"))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Подробности одного жеста.
struct GestureDetailView: View {
    @ObservedObject var model: AppModel
    @State private var draft: Gesture
    @State private var saveTask: Task<Void, Never>?
    @State private var directionsText: String
    @State private var appsText: String
    @State private var tab: Tab = .shape

    init(model: AppModel, gesture: Gesture) {
        self.model = model
        _draft = State(initialValue: gesture)
        _directionsText = State(initialValue: gesture.directions.joined(separator: ", "))
        _appsText = State(initialValue: gesture.apps.joined(separator: "\n"))
    }

    var body: some View {
        VStack(spacing: 0) {
            // Вкладки Росчерк / Действия / Меню — как в версиях для Linux и
            // Windows. Здесь это сегментированный переключатель: на маке
            // подчёркнутые вкладки внутри окна выглядят чужими, а деление
            // страницы то же самое.
            Picker("", selection: $tab) {
                ForEach(Tab.allCases, id: \.self) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            switch tab {
            case .shape: shapePage
            case .actions: actionsPage
            case .menu: menuPage
            }
        }
        .onChange(of: draft) { _ in scheduleSave() }
        .onChange(of: directionsText) { text in
            draft.directions = text
                .split(whereSeparator: { $0 == "," || $0 == " " })
                .map { $0.trimmingCharacters(in: .whitespaces).uppercased() }
                .filter { !$0.isEmpty }
        }
        .onChange(of: appsText) { text in
            draft.apps = text.split(separator: "\n")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
        }
    }

    // MARK: - Вкладки

    enum Tab: String, CaseIterable {
        case shape, actions, menu

        var title: String {
            switch self {
            case .shape: return tr("Росчерк")
            case .actions: return tr("Действия")
            case .menu: return tr("Меню")
            }
        }
    }

    private var shapePage: some View {
        Form {
            Section(tr("Жест")) {
                TextField(tr("Название"), text: $draft.name)
                TextField(tr("Описание"), text: $draft.describedAs, axis: .vertical)
                    .lineLimit(1...4)
                Toggle(tr("Включён"), isOn: $draft.enabled)
            }

            Section(tr("Фигура")) {
                TextField(tr("Направления"), text: $directionsText, prompt: Text(tr("например: D-R")))
                Text(tr("Буквы направлений через дефис: R вправо, L влево, U вверх, D вниз, ")
                     + tr("DR вниз-вправо и так далее. Несколько вариантов — через запятую."))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                StrokeCanvas(templates: $draft.templates)

                if let warning = conflictWarning {
                    Label(warning, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                        .font(.callout)
                }
            }

            Section(tr("Где работает")) {
                TextField(tr("Программы"), text: $appsText, axis: .vertical)
                    .lineLimit(2...6)
                Button(tr("Выбрать окно…")) { pickWindow() }
                    .help(tr("Нажмите и щёлкните по нужному окну"))
                Text(tr("Пусто — жест работает везде. По строке на программу: ")
                     + tr("«class:com.apple.Safari» — точное совпадение, иначе строка понимается ")
                     + tr("как выражение и ищется в «программа | заголовок окна». Имя программы ")
                     + tr("видно в журнале, когда жест срабатывает."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section(tr("Тонкости")) {
                HStack {
                    Text(tr("Допуск поворота"))
                    Spacer()
                    Text("\(Int(draft.rotationTolerance))°")
                        .foregroundStyle(.secondary)
                }
                Slider(value: $draft.rotationTolerance, in: 0...45, step: 1)
                Text(tr("Насколько криво можно рисовать. Больше 45° делать не стоит: ")
                     + tr("жест начнёт путаться со своим же поворотом."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }

    private var actionsPage: some View {
        Form {
            Section(tr("Действия")) {
                ActionsEditor(actions: $draft.actions)
            }
        }
        .formStyle(.grouped)
    }

    private var menuPage: some View {
        Form {
            Section(tr("Меню")) {
                Text(tr("Если есть пункты, жест открывает меню у курсора: выберите пункт — ")
                     + tr("выполнятся его действия. Без пунктов жест просто делает свои действия."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                MenuEditor(menu: $draft.menu)
            }
        }
        .formStyle(.grouped)
    }

    /// Подставить программу под курсором строкой «class:…».
    ///
    /// Правим текстовое поле, а не сразу список: человек видит добавленную
    /// строку там же, где правит остальные, и может её стереть тем же способом.
    private func pickWindow() {
        WindowPicker.pick { name in
            guard let name, !name.isEmpty else { return }
            let line = "class:\(name)"
            var lines = appsText
                .split(separator: "\n")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            guard !lines.contains(line) else { return }
            lines.append(line)
            appsText = lines.joined(separator: "\n")
        }
    }

    /// Сохранение с задержкой: пока человек печатает название, файл трогать не
    /// надо — иначе на каждую букву уходила бы запись на диск.
    private func scheduleSave() {
        saveTask?.cancel()
        let snapshot = draft
        saveTask = Task {
            try? await Task.sleep(nanoseconds: 600_000_000)
            if Task.isCancelled { return }
            model.update(snapshot)
        }
    }

    private var conflictWarning: String? {
        let mine = Set(draft.directions)
        guard !mine.isEmpty else { return nil }
        let clashing = model.gestures
            .filter { $0.enabled && $0.id != draft.id && !Set($0.directions).isDisjoint(with: mine) }
            .map(\.name)
        guard !clashing.isEmpty else { return nil }
        return "\(tr("Та же фигура у:")) \(clashing.joined(separator: ", ")). "
            + tr("Пока фигуры совпадают, не сработает ни один из жестов.")
    }
}

/// Список действий жеста.
struct ActionsEditor: View {
    @Binding var actions: [Action]

    private let types: [(value: String, title: String)] = [
        ("standard", tr("Стандартное действие")),
        ("keys", tr("Клавиши")),
        ("text", tr("Текст")),
        ("command", tr("Команда")),
        ("app", tr("Программа")),
        ("window", tr("Окно")),
        ("button", tr("Щелчок")),
        ("scroll", tr("Прокрутка")),
        ("delay", tr("Пауза, мс")),
        ("none", tr("Ничего")),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(actions.indices, id: \.self) { index in
                HStack(spacing: 8) {
                    Picker("", selection: $actions[index].type) {
                        ForEach(types, id: \.value) { type in
                            Text(type.title).tag(type.value)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 130)

                    if actions[index].type == "standard" {
                        // У стандартного действия значение выбирается из списка:
                        // помнить, что «вставить» — это ⌘V, человек не обязан,
                        // а такой жест ещё и переносится на другую систему.
                        Picker("", selection: $actions[index].value) {
                            ForEach(StandardActions.all, id: \.id) { entry in
                                Text(StandardActions.describe(entry.id)).tag(entry.id)
                            }
                        }
                        .labelsHidden()
                    } else {
                        TextField(hint(for: actions[index].type), text: $actions[index].value)
                    }

                    Button {
                        actions.remove(at: index)
                    } label: {
                        Image(systemName: "minus.circle")
                    }
                    .buttonStyle(.borderless)
                }
            }

            Button {
                actions.append(Action(type: "standard", value: "copy"))
            } label: {
                Label(tr("Добавить действие"), systemImage: "plus")
            }
            .buttonStyle(.borderless)

            Text(tr("Стандартное действие выбирается из списка и переносится между ")
                 + tr("системами как есть. Клавиши пишутся через плюс: cmd+shift+t, ")
                 + tr("ctrl+Left, F5. Действия выполняются по порядку сверху вниз."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func hint(for type: String) -> String {
        switch type {
        case "keys": return tr("cmd+t")
        case "text": return tr("текст, который напечатать")
        case "command": return tr("команда оболочки")
        case "app": return tr("Safari или com.apple.Safari")
        case "window": return tr("minimize, close, fullscreen, activate")
        case "button": return tr("left, right, middle")
        case "scroll": return tr("up 3")
        case "delay": return tr("200")
        default: return ""
        }
    }
}

/// Строка набора жестов над списком.
///
/// Набор — это отдельная папка жестов. Держим его здесь, а не в настройках:
/// переключают набор ровно тогда, когда смотрят на список жестов, и уходить за
/// этим в другое окно было бы странно.
private struct ProfileBar: View {
    @ObservedObject var model: AppModel
    @Binding var askingName: Bool
    @Binding var confirmingRemoval: Bool

    var body: some View {
        HStack(spacing: 6) {
            Picker("", selection: selection) {
                Text(tr("Основной")).tag("")
                ForEach(model.profiles, id: \.self) { name in
                    Text(name).tag(name)
                }
            }
            .labelsHidden()

            Button {
                askingName = true
            } label: {
                Image(systemName: "plus")
            }
            .buttonStyle(.borderless)
            .help(tr("Новый набор жестов"))

            Button {
                confirmingRemoval = true
            } label: {
                Image(systemName: "minus")
            }
            .buttonStyle(.borderless)
            .disabled(model.activeProfile.isEmpty)
            .help(tr("Удалить набор"))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
    }

    /// Выбор набора сразу перечитывает жесты, поэтому связка своя, а не прямая
    /// на настройку: иначе список остался бы от прежнего набора.
    private var selection: Binding<String> {
        Binding(get: { model.activeProfile },
                set: { name in
                    guard name != model.activeProfile else { return }
                    model.switchProfile(to: name)
                })
    }
}

/// Пункты меню жеста: у каждого своё название и свои действия.
struct MenuEditor: View {
    @Binding var menu: [MenuItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(menu.indices, id: \.self) { index in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        TextField(tr("Название пункта"), text: $menu[index].name)
                        Button {
                            menu.remove(at: index)
                        } label: {
                            Image(systemName: "minus.circle")
                        }
                        .buttonStyle(.borderless)
                        .help(tr("Убрать пункт"))
                    }
                    ActionsEditor(actions: $menu[index].actions)
                }
                .padding(12)
                .background(Color.secondary.opacity(0.08),
                            in: RoundedRectangle(cornerRadius: 8))
            }

            Button {
                menu.append(MenuItem(name: tr("Пункт")))
            } label: {
                Label(tr("Добавить пункт"), systemImage: "plus")
            }
            .buttonStyle(.borderless)
        }
    }
}
