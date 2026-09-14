import XCTest
import CoreGraphics
@testable import GlyphstrokeCore
@testable import GlyphstrokeMac

/// Разбор сочетаний и то, что каждое стандартное действие действительно
/// разбирается: опечатка в таблице иначе всплыла бы только у человека, при
/// первом же жесте, и выглядела бы как «программа ничего не делает».
final class KeyMapTests: XCTestCase {
    func testSimpleCombination() {
        let combo = KeyMap.parse("cmd+t")
        XCTAssertEqual(combo?.key, 17)
        XCTAssertEqual(combo?.flags.contains(.maskCommand), true)
    }

    func testLinuxNamesAreUnderstood() {
        // Файлы жестов приходят и с Linux: ctrl там пишут именно так.
        XCTAssertEqual(KeyMap.parse("ctrl+c")?.flags.contains(.maskControl), true)
        XCTAssertEqual(KeyMap.parse("alt+Left")?.key, 123)
        XCTAssertEqual(KeyMap.parse("ctrl+Page_Up")?.key, 116)
    }

    func testUnknownKeyIsRefused() {
        XCTAssertNil(KeyMap.parse("cmd+такойнет"))
        XCTAssertNil(KeyMap.parse(""))
    }

    func testTwoKeysAtOnceAreRefused() {
        // «ctrl+a+b» — это опечатка; нажать половину хуже, чем не нажать ничего.
        XCTAssertNil(KeyMap.parse("cmd+a+b"))
    }

    func testEveryStandardCombinationParses() {
        var broken: [String] = []
        for entry in StandardActions.all where entry.kind == .keys {
            if KeyMap.parse(entry.value) == nil {
                broken.append("\(entry.id): \(entry.value)")
            }
        }
        XCTAssertEqual(broken, [])
    }

    func testStandardWindowCommandsAreKnownToTheRunner() {
        // Значения действий над окном должны быть из того набора, который
        // умеет ActionRunner, иначе действие тихо ничего не сделает.
        let supported = ["minimize", "close", "fullscreen", "unfullscreen", "activate", "maximize", "unmaximize"]
        for entry in StandardActions.all where entry.kind == .window {
            XCTAssertTrue(supported.contains(entry.value), "\(entry.id): \(entry.value)")
        }
    }
}
