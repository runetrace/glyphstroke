import XCTest
@testable import GlyphstrokeCore

/// Проверка обновлений: сравнение версий, разбор ответа, суточный перерыв.
final class UpdateCheckTests: XCTestCase {
    func testVersionParsing() {
        XCTAssertEqual(UpdateCheck.parse("0.7.0"), [0, 7, 0])
        XCTAssertEqual(UpdateCheck.parse("v1.2.3"), [1, 2, 3])
        XCTAssertEqual(UpdateCheck.parse(""), [0])
    }

    func testPrereleaseIsNotNewerThanRelease() {
        // «0.8.0-rc1» не должен выглядеть новее готовой 0.8.0.
        XCTAssertFalse(UpdateCheck.isNewer("0.8.0-rc1", than: "0.8.0"))
        XCTAssertTrue(UpdateCheck.isNewer("0.8.0", than: "0.7.9"))
        XCTAssertFalse(UpdateCheck.isNewer("0.7.0", than: "0.7.0"))
        XCTAssertTrue(UpdateCheck.isNewer("1.0", than: "0.9.9"))
        XCTAssertFalse(UpdateCheck.isNewer("0.9", than: "0.9.1"))
    }

    func testReleaseIsReadFromTheAnswer() {
        let json = """
        {"tag_name": "v0.9.0", "html_url": "https://example/0.9.0", "body": " что нового "}
        """.data(using: .utf8)!
        let release = UpdateCheck.release(fromJSON: json)
        XCTAssertEqual(release?.version, "0.9.0")
        XCTAssertEqual(release?.url?.absoluteString, "https://example/0.9.0")
        XCTAssertEqual(release?.notes, "что нового")
    }

    func testAnswerWithoutATagIsIgnored() {
        let json = #"{"message": "Not Found"}"#.data(using: .utf8)!
        XCTAssertNil(UpdateCheck.release(fromJSON: json))
        XCTAssertNil(UpdateCheck.release(fromJSON: Data("не json".utf8)))
    }

    func testIntervalIsRespected() {
        let defaults = UserDefaults(suiteName: "glyphstroke.tests.interval")!
        defaults.removePersistentDomain(forName: "glyphstroke.tests.interval")

        XCTAssertTrue(UpdateCheck.due(defaults: defaults), "ни разу не спрашивали")
        UpdateCheck.remember(nil, defaults: defaults)
        XCTAssertFalse(UpdateCheck.due(defaults: defaults))
        let later = Date().addingTimeInterval(UpdateCheck.interval + 1)
        XCTAssertTrue(UpdateCheck.due(now: later, defaults: defaults))
        // время перевели назад: лучше спросить, чем ждать сутки от будущего
        let earlier = Date().addingTimeInterval(-10_000)
        XCTAssertTrue(UpdateCheck.due(now: earlier, defaults: defaults))
    }

    func testPendingKeepsOnlyNewerVersions() {
        let defaults = UserDefaults(suiteName: "glyphstroke.tests.pending")!
        defaults.removePersistentDomain(forName: "glyphstroke.tests.pending")

        let release = UpdateCheck.Release(version: "9.9.9",
                                          url: URL(string: "https://example/9.9.9"),
                                          notes: "")
        UpdateCheck.remember(release, defaults: defaults)
        XCTAssertEqual(UpdateCheck.pending(currentVersion: "0.2.0", defaults: defaults)?.version,
                       "9.9.9")
        XCTAssertNil(UpdateCheck.pending(currentVersion: "9.9.9", defaults: defaults),
                     "своя же версия — не новость")
        XCTAssertNil(UpdateCheck.pending(currentVersion: "10.0.0", defaults: defaults))
    }

    func testAddressesAreBuiltFromTheRepository() {
        XCTAssertEqual(UpdateCheck.apiURL(repository: "runetrace/glyphstroke")?.absoluteString,
                       "https://api.github.com/repos/runetrace/glyphstroke/releases/latest")
        XCTAssertEqual(UpdateCheck.releasePage(repository: "a/b")?.absoluteString,
                       "https://github.com/a/b/releases/latest")
    }
}
