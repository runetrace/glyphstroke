import XCTest
@testable import GlyphstrokeCore

/// Хранилище: наборы жестов и то, что файл жеста переживает пересохранение.
///
/// Каждый разбор идёт во временном каталоге: настоящая папка настроек у
/// человека одна, и тест, который в неё пишет, однажды сотрёт чужие жесты.
final class StoreTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("glyphstroke-tests-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func makeStore() -> Store { Store(root: root) }

    // MARK: - Наборы жестов

    func testMainSetLivesInGestures() {
        let store = makeStore()
        XCTAssertEqual(store.gesturesDirectory.lastPathComponent, "gestures")
    }

    func testChosenSetSwitchesTheDirectory() {
        let store = makeStore()
        store.activeProfile = "работа"
        XCTAssertEqual(store.gesturesDirectory.lastPathComponent, "работа")
        XCTAssertEqual(store.gesturesDirectory.deletingLastPathComponent().lastPathComponent,
                       "profiles")
    }

    func testProfileNameLosesPathSeparators() {
        XCTAssertEqual(Store.cleanProfileName("наб/ор"), "набор")
        XCTAssertEqual(Store.cleanProfileName("  игры  "), "игры")
        XCTAssertEqual(Store.cleanProfileName(nil), "")
    }

    func testEmptyNameCreatesNothing() {
        let store = makeStore()
        XCTAssertEqual(store.createProfile("   "), "")
        XCTAssertTrue(store.availableProfiles().isEmpty)
    }

    func testCreatedProfilesAreListedAlphabetically() {
        let store = makeStore()
        store.createProfile("работа")
        store.createProfile("браузер")
        XCTAssertEqual(store.availableProfiles(), ["браузер", "работа"])
    }

    func testNewProfileTakesACopyOfTheGestures() throws {
        let store = makeStore()
        try store.prepareDirectories()
        try store.save(Gesture(name: "назад", directions: ["L"]))

        store.createProfile("игры", copyFrom: "")
        store.activeProfile = "игры"

        let copied = store.loadGestures()
        XCTAssertEqual(copied.map(\.name), ["назад"])
        // Копия, а не та же папка: правка в наборе не должна менять основной.
        XCTAssertNotEqual(copied.first?.fileURL?.deletingLastPathComponent(),
                          root.appendingPathComponent("gestures"))
    }

    func testProfileWithoutASourceStartsEmpty() {
        let store = makeStore()
        store.createProfile("пусто")
        store.activeProfile = "пусто"
        XCTAssertTrue(store.loadGestures().isEmpty)
    }

    func testRemovedProfileDisappears() {
        let store = makeStore()
        store.createProfile("временный")
        store.removeProfile("временный")
        XCTAssertTrue(store.availableProfiles().isEmpty)
    }

    func testChosenSetSurvivesSaving() throws {
        let store = makeStore()
        var settings = store.loadSettings()
        settings.activeProfile = "работа"
        try store.saveSettings(settings)

        // Другой объект хранилища — как после перезапуска программы.
        let again = Store(root: root)
        XCTAssertEqual(again.loadSettings().activeProfile, "работа")
        XCTAssertEqual(again.gesturesDirectory.lastPathComponent, "работа")
    }

    // MARK: - Меню жеста

    func testMenuSurvivesSaving() throws {
        let store = makeStore()
        try store.prepareDirectories()
        let gesture = Gesture(name: "буфер", directions: ["D"],
                              menu: [MenuItem(name: "Копировать",
                                              actions: [Action(type: "standard", value: "copy")]),
                                     MenuItem(name: "Вставить",
                                              actions: [Action(type: "standard", value: "paste")])])
        let url = try store.save(gesture)

        let read = try XCTUnwrap(Store.gesture(fromFile: url))
        XCTAssertEqual(read.menu.map(\.name), ["Копировать", "Вставить"])
        XCTAssertEqual(read.menu.first?.actions.first?.value, "copy")
    }

    func testGestureWithoutAMenuKeepsNoMenuKey() throws {
        let store = makeStore()
        try store.prepareDirectories()
        let url = try store.save(Gesture(name: "назад", directions: ["L"]))
        let text = try String(contentsOf: url, encoding: .utf8)
        // Пересохранение прежнего жеста не должно дописывать ему пустые ключи:
        // файл человека меняется только тогда, когда он сам что-то поменял.
        XCTAssertFalse(text.contains("menu"))
    }
}
