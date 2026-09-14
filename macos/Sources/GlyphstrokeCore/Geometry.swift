import Foundation

/// Точка росчерка в экранной системе координат: X вправо, Y вниз.
///
/// Своя структура, а не CGPoint: ядро не зависит от графических рамок
/// системы, и его тесты гоняются где угодно — в том числе там, где
/// CoreGraphics нет вовсе.
public struct Point: Equatable, Sendable {
    public var x: Double
    public var y: Double

    public init(_ x: Double, _ y: Double) {
        self.x = x
        self.y = y
    }

    public func distance(to other: Point) -> Double {
        hypot(other.x - x, other.y - y)
    }
}

/// Геометрия росчерка: всё, что нужно алгоритму $1.
///
/// Перенесено из версии для Linux (`glyphstroke/recognizer.py`) один в один —
/// числа и пороги обязаны совпадать, иначе один и тот же жест на двух
/// машинах распознавался бы по-разному, а файлы жестов у нас общие.
public enum Geometry {
    /// Сколько точек оставляем после выравнивания по длине пути.
    public static let numPoints = 64
    /// Сторона квадрата, в который вписывается росчерк перед сравнением.
    public static let squareSize = 250.0
    public static let halfDiagonal = 0.5 * hypot(squareSize, squareSize)
    /// Золотое сечение — для поиска лучшего угла.
    public static let phi = 0.5 * (-1.0 + 5.0.squareRoot())
    /// Росчерк вытянутее, чем 1:4, сжимаем равномерно: иначе прямая линия
    /// растянулась бы в квадрат и потеряла форму.
    public static let thinRatio = 0.25

    public static func pathLength(_ points: [Point]) -> Double {
        guard points.count > 1 else { return 0 }
        var total = 0.0
        for i in 1..<points.count {
            total += points[i - 1].distance(to: points[i])
        }
        return total
    }

    public static func dedupe(_ points: [Point], eps: Double = 1e-9) -> [Point] {
        var out: [Point] = []
        for p in points where out.isEmpty || out[out.count - 1].distance(to: p) > eps {
            out.append(p)
        }
        return out
    }

    /// Разложить росчерк на `n` равноудалённых по длине пути точек.
    public static func resample(_ points: [Point], n: Int = numPoints) -> [Point] {
        var pts = dedupe(points)
        guard pts.count >= 2 else {
            return Array(repeating: pts.first ?? Point(0, 0), count: n)
        }
        let interval = pathLength(pts) / Double(n - 1)
        guard interval > 0 else { return Array(repeating: pts[0], count: n) }

        var out: [Point] = [pts[0]]
        var accumulated = 0.0
        var i = 1
        while i < pts.count {
            let d = pts[i - 1].distance(to: pts[i])
            if accumulated + d >= interval {
                let t = (interval - accumulated) / d
                let next = Point(
                    pts[i - 1].x + t * (pts[i].x - pts[i - 1].x),
                    pts[i - 1].y + t * (pts[i].y - pts[i - 1].y)
                )
                out.append(next)
                // Точка вставляется в исходный список: следующий отрезок
                // отмеряется уже от неё, иначе шаг «уплывает».
                pts.insert(next, at: i)
                accumulated = 0
            } else {
                accumulated += d
            }
            i += 1
        }
        // Хвост добираем из-за накопленной ошибки вещественных чисел.
        while out.count < n {
            out.append(pts[pts.count - 1])
        }
        return Array(out.prefix(n))
    }

    public static func centroid(_ points: [Point]) -> Point {
        guard !points.isEmpty else { return Point(0, 0) }
        let count = Double(points.count)
        let sum = points.reduce(Point(0, 0)) { Point($0.x + $1.x, $0.y + $1.y) }
        return Point(sum.x / count, sum.y / count)
    }

    /// Левый верхний угол и размеры охватывающего прямоугольника.
    public static func boundingBox(_ points: [Point]) -> (x: Double, y: Double, width: Double, height: Double) {
        guard !points.isEmpty else { return (0, 0, 0, 0) }
        let xs = points.map(\.x)
        let ys = points.map(\.y)
        let minX = xs.min()!, maxX = xs.max()!
        let minY = ys.min()!, maxY = ys.max()!
        return (minX, minY, maxX - minX, maxY - minY)
    }

    public static func rotateBy(_ points: [Point], radians: Double) -> [Point] {
        let c = centroid(points)
        let cosA = cos(radians), sinA = sin(radians)
        return points.map { p in
            Point(
                (p.x - c.x) * cosA - (p.y - c.y) * sinA + c.x,
                (p.x - c.x) * sinA + (p.y - c.y) * cosA + c.y
            )
        }
    }

    public static func scaleToSquare(_ points: [Point], size: Double = squareSize) -> [Point] {
        let box = boundingBox(points)
        if box.width <= 0 && box.height <= 0 { return points }
        let longest = max(box.width, box.height)
        let thin = longest > 0 ? min(box.width, box.height) / longest < thinRatio : true
        if thin {
            // Вытянутый росчерк (прямая, узкая дуга) — только равномерное сжатие.
            let k = size / longest
            return points.map { Point($0.x * k, $0.y * k) }
        }
        return points.map { Point($0.x * size / box.width, $0.y * size / box.height) }
    }

    public static func translateToOrigin(_ points: [Point]) -> [Point] {
        let c = centroid(points)
        return points.map { Point($0.x - c.x, $0.y - c.y) }
    }

    /// Привести росчерк к виду, пригодному для сравнения с шаблоном.
    public static func normalize(_ points: [Point], n: Int = numPoints) -> [Point] {
        translateToOrigin(scaleToSquare(resample(points, n: n)))
    }

    public static func pathDistance(_ a: [Point], _ b: [Point]) -> Double {
        let count = min(a.count, b.count)
        guard count > 0 else { return .infinity }
        var total = 0.0
        for i in 0..<count {
            total += a[i].distance(to: b[i])
        }
        return total / Double(a.count)
    }

    public static func distanceAtAngle(_ points: [Point], template: [Point], angle: Double) -> Double {
        pathDistance(rotateBy(points, radians: angle), template)
    }

    /// Поиск золотым сечением по углу в пределах ±`tolerance`.
    ///
    /// Допуск маленький (по умолчанию 20°): он гасит дрожание руки, но не
    /// позволяет спутать жест с его же поворотом на 90°.
    public static func distanceAtBestAngle(
        _ points: [Point],
        template: [Point],
        tolerance: Double,
        precision: Double = 2.0 * .pi / 180.0
    ) -> Double {
        let straight = distanceAtAngle(points, template: template, angle: 0)
        guard tolerance > 0 else { return straight }

        var lo = -tolerance, hi = tolerance
        var x1 = phi * lo + (1.0 - phi) * hi
        var f1 = distanceAtAngle(points, template: template, angle: x1)
        var x2 = (1.0 - phi) * lo + phi * hi
        var f2 = distanceAtAngle(points, template: template, angle: x2)

        while abs(hi - lo) > precision {
            if f1 < f2 {
                hi = x2
                x2 = x1
                f2 = f1
                x1 = phi * lo + (1.0 - phi) * hi
                f1 = distanceAtAngle(points, template: template, angle: x1)
            } else {
                lo = x1
                x1 = x2
                f1 = f2
                x2 = (1.0 - phi) * lo + phi * hi
                f2 = distanceAtAngle(points, template: template, angle: x2)
            }
        }
        // Угол 0 проверяем отдельно: поиск в него не попадает и слегка портит
        // оценку даже при точном совпадении росчерка с шаблоном.
        return min(straight, min(f1, f2))
    }
}
