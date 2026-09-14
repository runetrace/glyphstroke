import SwiftUI
import ServiceManagement
import GlyphstrokeCore
import GlyphstrokeMac


/// Состояние интерфейса: жесты, настройки и связь с работающим перехватом.
///
/// Редактор правит те же файлы, что читает демон, поэтому после каждой записи
/// движку говорится перечитать набор. Иначе получалось бы худшее из возможного:
/// человек поменял жест, увидел изменение на экране, а мышь продолжает
/// выполнять старое — и понять, почему, нельзя.
@MainActor
final class AppModel: ObservableObject {
    let store: Store
    private weak var engine: GestureEngine?

    @Published var gestures: [Gesture] = []
    /// Заведённые наборы, кроме основного. Держим списком, а не читаем каталог
    /// на каждую перерисовку: строка набора рисуется часто, обращение к диску
    /// в такой дороге лишнее.
    @Published var profiles: [String] = []
    @Published var settings: Settings
    @Published var selectedID: String?
    /// Последнее сообщение о неудаче — показывается в редакторе полоской.
    @Published var problem: String?

    init(store: Store, engine: GestureEngine?) {
        self.store = store
        self.engine = engine
        self.settings = store.loadSettings()
        reload()
    }

    var selected: Gesture? {
        gestures.first { $0.id == selectedID }
    }

    func reload() {
        // Настройки первыми: в них лежит выбранный набор, а от него зависит,
        // из какой папки читаются жесты.
        settings = store.loadSettings()
        gestures = store.loadGestures()
        profiles = store.availableProfiles()
        if selectedID == nil || !gestures.contains(where: { $0.id == selectedID }) {
            selectedID = gestures.first?.id
        }
    }

    // MARK: - Наборы жестов

    /// Выбранный набор; пустая строка — основной.
    var activeProfile: String { settings.activeProfile }

    func switchProfile(to name: String) {
        settings.activeProfile = name
        do {
            try store.saveSettings(settings)
            try store.prepareDirectories()
            problem = nil
        } catch {
            // Выбор набора записать не удалось — жесты всё равно перечитаем,
            // иначе редактор показывал бы чужой список.
            store.activeProfile = name
            problem = "\(tr("Не удалось сохранить настройки:")) \(error.localizedDescription)"
        }
        selectedID = nil
        reload()
        engine?.reload()
    }

    /// Новый набор создаётся копией текущего: начинать с пустого списка человек
    /// обычно не хочет — он заводит набор, чтобы поменять пару жестов.
    func addProfile(named name: String) {
        let created = store.createProfile(name, copyFrom: settings.activeProfile)
        guard !created.isEmpty else { return }
        switchProfile(to: created)
    }

    func removeActiveProfile() {
        let name = settings.activeProfile
        guard !name.isEmpty else { return }
        store.removeProfile(name)
        switchProfile(to: "")
    }

    // MARK: - Жесты

    func update(_ gesture: Gesture) {
        guard let index = gestures.firstIndex(where: { $0.id == gesture.id }) else { return }
        gestures[index] = gesture
        save(gesture)
    }

    func save(_ gesture: Gesture) {
        do {
            let url = try store.save(gesture)
            if let index = gestures.firstIndex(where: { $0.id == gesture.id }) {
                gestures[index].fileURL = url
            }
            selectedID = gestures.first(where: { $0.fileURL == url })?.id ?? selectedID
            engine?.reload()
            problem = nil
        } catch {
            problem = "\(tr("Не удалось сохранить")) «\(gesture.name)»: \(error.localizedDescription)"
        }
    }

    func addGesture() {
        let gesture = Gesture(name: uniqueName(base: tr("Новый жест")),
                              describedAs: "",
                              fileURL: nil)
        save(gesture)
        reload()
        selectedID = gestures.first(where: { $0.name == gesture.name })?.id
    }

    func duplicate(_ gesture: Gesture) {
        var copy = gesture
        copy.name = uniqueName(base: gesture.name)
        copy.fileURL = nil
        save(copy)
        reload()
        selectedID = gestures.first(where: { $0.name == copy.name })?.id
    }

    func delete(_ gesture: Gesture) {
        if let url = gesture.fileURL {
            try? FileManager.default.removeItem(at: url)
        }
        reload()
        engine?.reload()
    }

    private func uniqueName(base: String) -> String {
        var candidate = base
        var counter = 2
        while gestures.contains(where: { $0.name == candidate }) {
            candidate = "\(base) \(counter)"
            counter += 1
        }
        return candidate
    }

    /// Жесты, у которых совпадают фигуры: такая пара не сработает никогда —
    /// распознаватель отказывается выбирать между двумя равными.
    var conflicts: [String: [String]] {
        var byCode: [String: [String]] = [:]
        for gesture in gestures where gesture.enabled {
            for code in gesture.directions where !code.isEmpty {
                byCode[code, default: []].append(gesture.name)
            }
        }
        return byCode.filter { $0.value.count > 1 }
    }

    // MARK: - Настройки

    func saveSettings() {
        do {
            try store.saveSettings(settings)
            engine?.reload()
            problem = nil
        } catch {
            problem = "\(tr("Не удалось сохранить настройки:")) \(error.localizedDescription)"
        }
    }

    // MARK: - Автозапуск

    /// Запускается ли программа при входе в систему.
    ///
    /// Через SMAppService, а не через ярлык в «Объектах входа»: система сама
    /// следит за записью, и при переносе программы в другую папку она не
    /// теряется.
    var launchesAtLogin: Bool {
        SMAppService.mainApp.status == .enabled
    }

    func setLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            objectWillChange.send()
        } catch {
            problem = "\(tr("Автозапуск не изменился:")) \(error.localizedDescription). "
                + tr("Так бывает, если программа запущена не из папки «Программы».")
        }
    }
}

/// Жест в списках SwiftUI. Опознаём по файлу: имя человек меняет на ходу, и
/// выделение перескакивало бы на чужую строку прямо посреди правки.
extension Gesture: Identifiable {
    public var id: String { fileURL?.path ?? "новый:" + name }
}
