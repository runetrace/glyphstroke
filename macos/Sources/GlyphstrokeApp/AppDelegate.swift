import AppKit
import SwiftUI
import GlyphstrokeCore
import GlyphstrokeMac

/// Приложение без окна: значок в строке меню и перехват мыши.
///
/// Программа живёт в строке меню, а не в Dock: она нужна всё время и почти
/// никогда — глазами. Значок при этом обязателен. Невидимая программа,
/// которая перехватывает мышь, выглядит поломкой системы: человеку нужно
/// одним движением увидеть, работает она сейчас или на паузе, и одним же
/// движением её выключить.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let store = Store()
    private var engine: GestureEngine!
    private var model: AppModel!
    private var windows: Windows!
    private var statusItem: NSStatusItem!
    private var logLines: [String] = []
    private var logWindow: NSWindow?
    private var logView: NSTextView?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Язык интерфейса — до построения меню и окон.
        L.use(store.loadSettings().language)

        installStarterGesturesIfNeeded()

        engine = GestureEngine(store: store)
        engine.onLog = { [weak self] message in
            DispatchQueue.main.async { self?.append(log: message) }
        }

        model = AppModel(store: store, engine: engine)
        windows = Windows(model: model)

        buildStatusItem()
        startEngineOrExplain()
        scheduleUpdateCheck()
    }

    func applicationWillTerminate(_ notification: Notification) {
        engine?.stop()
    }

    // MARK: - Запуск

    private func startEngineOrExplain() {
        guard Permissions.allGranted else {
            windows.showOnboarding()
            refreshStatusItem()
            return
        }
        do {
            try engine.start()
        } catch {
            append(log: "перехват не включился: \(error)")
            windows.showOnboarding()
        }
        refreshStatusItem()
    }

    /// Стартовый набор кладём при первом запуске.
    ///
    /// Он маковский: сочетания клавиш на маке другие, и жесты, перенесённые
    /// с Linux один в один, нажимали бы не то. Файлы от Linux при этом
    /// читаются как есть — формат общий, разойтись могут только сочетания.
    private func installStarterGesturesIfNeeded() {
        // Bundle.module — когда программа запущена как пакет SwiftPM,
        // Bundle.main — когда собрана в .app.
        let directory = Bundle.module.url(forResource: "gestures", withExtension: nil)
            ?? Bundle.main.url(forResource: "gestures", withExtension: nil)
        guard let directory else { return }
        if let copied = try? store.installStarterGestures(from: directory), copied > 0 {
            append(log: "положен стартовый набор жестов: \(copied)")
        }
    }

    // MARK: - Строка меню

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "scribble.variable", accessibilityDescription: "Glyphstroke")
            button.image?.isTemplate = true
        }
        refreshStatusItem()
    }

    private func refreshStatusItem() {
        let menu = NSMenu()

        let state: String
        if !Permissions.allGranted {
            state = tr("Нет разрешений")
        } else if engine.paused {
            state = tr("На паузе")
        } else if engine.isRunning {
            state = "\(tr("Жестов загружено:")) \(engine.gestureCount)"
        } else {
            state = tr("Перехват не включён")
        }
        let header = NSMenuItem(title: state, action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(.separator())

        let pause = NSMenuItem(title: engine.paused ? tr("Продолжить") : tr("Пауза"),
                               action: #selector(togglePause), keyEquivalent: "")
        pause.target = self
        menu.addItem(pause)

        let editor = NSMenuItem(title: tr("Жесты…"), action: #selector(showEditor), keyEquivalent: "")
        editor.target = self
        menu.addItem(editor)

        let preferences = NSMenuItem(title: tr("Настройки…"), action: #selector(showSettings), keyEquivalent: ",")
        preferences.target = self
        menu.addItem(preferences)

        let reload = NSMenuItem(title: tr("Перечитать жесты"), action: #selector(reloadGestures), keyEquivalent: "")
        reload.target = self
        menu.addItem(reload)

        let logItem = NSMenuItem(title: tr("Журнал…"), action: #selector(showLog), keyEquivalent: "")
        logItem.target = self
        menu.addItem(logItem)

        let helpItem = NSMenuItem(title: tr("Справка…"), action: #selector(showHelp), keyEquivalent: "?")
        helpItem.target = self
        menu.addItem(helpItem)

        if !Permissions.allGranted {
            let permissions = NSMenuItem(title: tr("Выдать разрешения…"), action: #selector(showOnboarding), keyEquivalent: "")
            permissions.target = self
            menu.addItem(permissions)
        }

        menu.addItem(.separator())
        let updates = NSMenuItem(title: tr("Проверить обновления…"), action: #selector(checkUpdatesNow),
                                 keyEquivalent: "")
        updates.target = self
        menu.addItem(updates)

        let about = NSMenuItem(title: tr("О программе…"), action: #selector(showAbout), keyEquivalent: "")
        about.target = self
        menu.addItem(about)

        let quit = NSMenuItem(title: tr("Выйти"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quit)

        statusItem.menu = menu
    }

    @objc private func togglePause() {
        engine.setPaused(!engine.paused)
        refreshStatusItem()
    }

    @objc private func reloadGestures() {
        engine.reload()
        model.reload()
        refreshStatusItem()
    }

    @objc private func showEditor() {
        windows.showEditor()
    }

    @objc private func showHelp() {
        windows.showHelp()
    }

    @objc private func showSettings() {
        windows.showSettings()
    }

    // MARK: - Обновления

    /// Раз в сутки узнавать, не вышла ли версия новее.
    ///
    /// Первый запрос — с задержкой: при входе в систему сеть обычно ещё не
    /// поднялась, да и мешать старту сеанса незачем. Сама программа не
    /// обновляется, поэтому всё, что делает проверка, — показывает окно с
    /// вопросом, открыть ли страницу загрузки.
    private func scheduleUpdateCheck() {
        runUpdateCheck(force: false, announceSilence: false)
        Timer.scheduledTimer(withTimeInterval: UpdateCheck.interval, repeats: true) { [weak self] _ in
            DispatchQueue.main.async { self?.runUpdateCheck(force: false, announceSilence: false) }
        }
    }

    @objc private func checkUpdatesNow() {
        runUpdateCheck(force: true, announceSilence: true)
    }

    private func runUpdateCheck(force: Bool, announceSilence: Bool) {
        let settings = store.loadSettings()
        guard force || settings.checkUpdates else { return }
        guard force || UpdateCheck.due() else {
            showUpdateIfPending()
            return
        }
        let repository = settings.updateRepo.isEmpty
            ? UpdateCheck.defaultRepository : settings.updateRepo

        let delay: DispatchTime = force ? .now() : .now() + 30
        DispatchQueue.main.asyncAfter(deadline: delay) { [weak self] in
            UpdateCheck.fetch(repository: repository) { release in
                DispatchQueue.main.async {
                    UpdateCheck.remember(release)
                    guard let self else { return }
                    let current = Bundle.main.shortVersion
                    if let release, UpdateCheck.isNewer(release.version, than: current) {
                        self.append(log: "вышла версия \(release.version), установлена \(current)")
                        self.offer(update: release, repository: repository)
                    } else if announceSilence {
                        self.reportLatestVersion(current)
                    }
                }
            }
        }
    }

    private func showUpdateIfPending() {
        guard let release = UpdateCheck.pending(currentVersion: Bundle.main.shortVersion) else { return }
        let settings = store.loadSettings()
        let repository = settings.updateRepo.isEmpty
            ? UpdateCheck.defaultRepository : settings.updateRepo
        offer(update: release, repository: repository)
    }

    /// Спросить, а не поставить: программа держит мышь, и подменять её у
    /// человека за спиной нельзя.
    private func offer(update release: UpdateCheck.Release, repository: String) {
        let alert = NSAlert()
        alert.messageText = "\(tr("Вышла версия")) \(release.version)"
        let notes = release.notes.isEmpty ? "" : "\n\n" + release.notes.prefix(600)
        alert.informativeText = "\(tr("Установлена")) \(Bundle.main.shortVersion). "
            + tr("Обновление ставится вручную: программа не заменяет себя сама.") + notes
        alert.addButton(withTitle: tr("Открыть страницу загрузки"))
        alert.addButton(withTitle: tr("Позже"))

        NSApp.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertFirstButtonReturn,
           let url = release.url ?? UpdateCheck.releasePage(repository: repository) {
            NSWorkspace.shared.open(url)
        }
    }

    private func reportLatestVersion(_ current: String) {
        let alert = NSAlert()
        alert.messageText = "\(tr("Установлена последняя версия")) \(current)"
        alert.informativeText = tr("Новых выпусков нет — или сервер не ответил.")
        alert.addButton(withTitle: tr("Понятно"))
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    /// Штатное окно «О программе»: значок берётся из пакета сам, описание и
    /// адрес для писем кладём в поле сведений.
    @objc private func showAbout() {
        NSApp.activate(ignoringOtherApps: true)
        let credits = NSAttributedString(
            string: tr("Управление устройством жестами\n\n")
                + tr("Вопросы и сообщения об ошибках: runetrace@proton.me"),
            attributes: [.font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)])
        NSApp.orderFrontStandardAboutPanel(options: [.credits: credits])
    }

    // MARK: - Разрешения

    @objc private func showOnboarding() {
        windows.showOnboarding()
        refreshStatusItem()
    }

    // MARK: - Журнал

    private func append(log message: String) {
        let stamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        logLines.append("\(stamp)  \(message)")
        // Журнал нужен для разбора «почему не сработало», а не для истории:
        // держим последнюю сотню строк и не растём в памяти.
        if logLines.count > 100 {
            logLines.removeFirst(logLines.count - 100)
        }
        logView?.string = logLines.joined(separator: "\n")
        logView?.scrollToEndOfDocument(nil)
    }

    @objc private func showLog() {
        if let logWindow {
            logWindow.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let frame = NSRect(x: 0, y: 0, width: 620, height: 360)
        let window = NSWindow(contentRect: frame,
                              styleMask: [.titled, .closable, .resizable],
                              backing: .buffered, defer: false)
        window.title = tr("Glyphstroke — журнал")
        window.isReleasedWhenClosed = false

        let scroll = NSScrollView(frame: frame)
        scroll.hasVerticalScroller = true
        scroll.autoresizingMask = [.width, .height]

        let text = NSTextView(frame: frame)
        text.isEditable = false
        text.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        text.string = logLines.joined(separator: "\n")
        scroll.documentView = text

        window.contentView = scroll
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        logWindow = window
        logView = text
    }
}
