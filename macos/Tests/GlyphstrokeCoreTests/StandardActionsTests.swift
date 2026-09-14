import XCTest
@testable import GlyphstrokeCore

/// Стандартные действия: состав таблицы и совпадение с версией для Linux.
final class StandardActionsTests: XCTestCase {
    /// Список имён, записанный в `glyphstroke/standard.py` версии для Linux.
    ///
    /// Пусть лежит здесь копией: разъехавшиеся имена — это молча переставший
    /// работать жест, перенесённый с другой машины, а такую поломку человек
    /// не свяжет с обновлением. Меняется список — правятся обе стороны и эта
    /// строка, и тогда правка видна в истории.
    static let expectedIDs = [
        "copy", "cut", "paste", "delete", "undo", "redo", "select-all",
        "new", "open", "save", "print", "find",
        "new-tab", "close-tab", "next-tab", "prev-tab", "back", "forward", "refresh",
        "zoom-in", "zoom-out", "zoom-reset",
        "minimize", "maximize", "unmaximize", "fullscreen", "close-window", "switch-window",
        "quit", "screenshot",
    ]

    func testIDsMatchTheLinuxTable() {
        XCTAssertEqual(StandardActions.all.map(\.id), Self.expectedIDs)
    }

    func testEveryEntryIsFound() {
        for id in Self.expectedIDs {
            XCTAssertNotNil(StandardActions.entry(id), id)
        }
    }

    func testNameIsCaseInsensitive() {
        XCTAssertEqual(StandardActions.entry("Copy")?.id, "copy")
        XCTAssertEqual(StandardActions.entry("  PASTE ")?.id, "paste")
    }

    func testUnknownNameIsNotFound() {
        XCTAssertNil(StandardActions.entry("потанцевать"))
        XCTAssertNil(StandardActions.entry(""))
    }

    func testWindowActionsUseTheWindowKind() {
        // Свернуть и развернуть окно клавишами на маке не делают: это работа
        // Универсального доступа.
        for id in ["minimize", "maximize", "unmaximize", "fullscreen", "close-window"] {
            XCTAssertEqual(StandardActions.entry(id)?.kind, .window, id)
        }
    }

    func testEditingActionsUseCommand() {
        // ⌘, а не ctrl: это и есть причина, по которой таблица для мака своя.
        for id in ["copy", "cut", "paste", "undo", "select-all", "save"] {
            let value = StandardActions.entry(id)?.value ?? ""
            XCTAssertTrue(value.hasPrefix("cmd+"), "\(id): \(value)")
        }
    }

    func testDescriptionShowsTheCombination() {
        XCTAssertEqual(StandardActions.describe("paste"), "Вставить — ⌘V")
        XCTAssertEqual(StandardActions.describe("prev-tab"), "Предыдущая вкладка — ⌘⇧[")
        XCTAssertEqual(StandardActions.describe("delete"), "Удалить — ⌫")
    }

    func testWindowActionsHaveNoCombinationToShow() {
        XCTAssertEqual(StandardActions.describe("minimize"), "Свернуть окно")
    }

    func testSymbolsKeepModifiersBeforeTheKey() {
        XCTAssertEqual(StandardActions.symbols("cmd+shift+z"), "⌘⇧Z")
        XCTAssertEqual(StandardActions.symbols("ctrl+alt+left"), "⌃⌥←")
        XCTAssertEqual(StandardActions.symbols("f5"), "F5")
    }

    func testTitleFallsBackToTheName() {
        XCTAssertEqual(StandardActions.title("copy"), "Копировать")
        XCTAssertEqual(StandardActions.title("нет-такого"), "нет-такого")
    }
}
