import XCTest
@testable import GlyphstrokeCore

/// Проверки распознавания — те же, что в версии для Linux.
///
/// Смысл не в том, чтобы проверить арифметику ещё раз, а в том, чтобы
/// зафиксировать совпадение двух портов: файл жеста, нарисованный на одной
/// машине, обязан срабатывать на другой. Разъедутся пороги — разъедутся и
/// жесты, причём молча.
final class RecognizerTests: XCTestCase {
    // MARK: - Помощники

    func line(_ x0: Double, _ y0: Double, _ x1: Double, _ y1: Double, count: Int = 40) -> [Point] {
        (0..<count).map { i in
            let t = Double(i) / Double(count - 1)
            return Point(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        }
    }

    /// Дрожание руки: повторяемое, без случайных чисел — иначе тест то падает,
    /// то нет, и верить ему нельзя.
    func shaky(_ points: [Point], amount: Double = 1.5) -> [Point] {
        points.enumerated().map { index, point in
            let phase = Double(index)
            return Point(point.x + amount * sin(phase * 1.7),
                         point.y + amount * cos(phase * 2.3))
        }
    }

    // MARK: - Геометрия

    func testResampleGivesUniformSpacing() {
        let points = Geometry.resample(line(0, 0, 300, 0), n: 64)
        XCTAssertEqual(points.count, 64)
        var gaps: [Double] = []
        for i in 1..<points.count {
            gaps.append(points[i - 1].distance(to: points[i]))
        }
        XCTAssertLessThan(gaps.max()! - gaps.min()!, 1e-6)
    }

    func testPathLengthOfCorner() {
        let stroke = line(0, 0, 0, 100) + line(0, 100, 100, 100)
        XCTAssertEqual(Geometry.pathLength(stroke), 200, accuracy: 1.0)
    }

    // MARK: - Коды направлений

    func testDirectionCodes() {
        XCTAssertEqual(DirectionCode.of(line(0, 0, 200, 0)), "R")
        XCTAssertEqual(DirectionCode.of(line(0, 0, -200, 0)), "L")
        XCTAssertEqual(DirectionCode.of(line(0, 0, 0, 200)), "D")
        XCTAssertEqual(DirectionCode.of(line(0, 0, 0, -200)), "U")
        XCTAssertEqual(DirectionCode.of(line(0, 0, 150, 150)), "DR")
        XCTAssertEqual(DirectionCode.of(line(0, 0, -150, 150)), "DL")
        XCTAssertEqual(DirectionCode.of(line(0, 0, 0, 200) + line(0, 200, 200, 200)), "D-R")
    }

    func testDirectionCodeIsScaleIndependent() {
        let small = DirectionCode.of(line(0, 0, 0, 60) + line(0, 60, 60, 60))
        let large = DirectionCode.of(line(0, 0, 0, 600) + line(0, 600, 600, 600))
        XCTAssertEqual(small, large)
    }

    func testEmptyStrokeHasNoCode() {
        XCTAssertEqual(DirectionCode.of([]), "")
        XCTAssertEqual(DirectionCode.of([Point(10, 10)]), "")
    }

    func testOctantDistanceWrapsAround() {
        XCTAssertEqual(DirectionCode.distance("R", "R"), 0)
        XCTAssertEqual(DirectionCode.distance("R", "UR"), 1)
        XCTAssertEqual(DirectionCode.distance("R", "L"), 4)
        XCTAssertEqual(DirectionCode.distance("UR", "DR"), 2)
    }

    func testShakyHandStillMatches() {
        // Хвост линии уводит вбок — это по-прежнему тот же жест.
        XCTAssertGreaterThan(DirectionCode.similarity(drawn: "L-DL", target: "L"), 0.8)
        XCTAssertGreaterThan(DirectionCode.similarity(drawn: "D-DR-R", target: "D-R"), 0.8)
    }

    func testDifferentShapesDoNotMatch() {
        XCTAssertLessThan(DirectionCode.similarity(drawn: "L", target: "R"), 0.5)
        XCTAssertLessThan(DirectionCode.similarity(drawn: "D-R", target: "U-L"), 0.5)
    }

    // MARK: - Шаблоны

    func testTemplateMatchesItself() {
        let stroke = line(0, 0, 0, 200) + line(0, 200, 200, 200)
        let distance = Geometry.distanceAtBestAngle(Geometry.normalize(stroke),
                                                    template: Geometry.normalize(stroke),
                                                    tolerance: 20.0 * .pi / 180.0)
        XCTAssertLessThan(distance, 1e-6)
    }

    func testTemplateToleratesSizeAndShift() {
        let template = Geometry.normalize(line(0, 0, 0, 200) + line(0, 200, 200, 200))
        let drawn = Geometry.normalize(line(500, 500, 500, 600) + line(500, 600, 600, 600))
        let distance = Geometry.distanceAtBestAngle(drawn, template: template,
                                                    tolerance: 20.0 * .pi / 180.0)
        // Та же фигура вдвое мельче и в другом углу экрана — это тот же жест:
        // нормализация снимает и размер, и положение. На эталонной реализации
        // оценка здесь ровно 1.0.
        XCTAssertGreaterThan(1.0 - distance / Geometry.halfDiagonal, 0.99)
    }

    // MARK: - Сопоставление целиком

    func recognizer() -> Recognizer {
        Recognizer(gestures: [
            GestureDefinition(name: "Назад", directions: ["L"]),
            GestureDefinition(name: "Вперёд", directions: ["R"]),
            GestureDefinition(name: "Новая вкладка", directions: ["U"]),
            GestureDefinition(name: "Свернуть окно", directions: ["L-D"]),
        ])
    }

    func testStraightStrokeFiresItsGesture() {
        let match = recognizer().recognize(line(0, 0, -200, 0))
        XCTAssertEqual(match.name, "Назад")
        XCTAssertEqual(match.code, "L")
    }

    func testWobblyStrokeFiresTheIntendedGesture() {
        let match = recognizer().recognize(shaky(line(0, 0, -220, 6)))
        XCTAssertEqual(match.name, "Назад")
    }

    func testUnknownStrokeReturnsNothing() {
        // Диагональ не описана ни одним жестом набора.
        let match = recognizer().recognize(line(0, 0, 150, 150))
        XCTAssertNil(match.name)
        XCTAssertEqual(match.code, "DR")
    }

    func testAmbiguousStrokeFiresNothing() {
        // Два жеста с одинаковой фигурой: сработать не должен ни один —
        // наугад выполнять чужое действие хуже, чем не выполнить ничего.
        let engine = Recognizer(gestures: [
            GestureDefinition(name: "Первый", directions: ["L"]),
            GestureDefinition(name: "Второй", directions: ["L"]),
        ])
        let match = engine.recognize(line(0, 0, -200, 0))
        XCTAssertNil(match.name)
        XCTAssertNotNil(match.runnerUp)
    }

    func testUnrecognizedReportsTheClosestGesture() {
        let match = recognizer().recognize(line(0, 0, 140, 140))
        XCTAssertNil(match.name)
        XCTAssertNotNil(match.runnerUp, "человеку надо показать, чего не хватило")
    }
}
