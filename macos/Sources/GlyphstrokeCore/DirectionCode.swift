import Foundation

/// Код направлений: росчерк как строка октантов вида `D-R` — «вниз, потом
/// вправо».
///
/// Таким жестом можно описать фигуру текстом, ничего не рисуя, — на этом
/// держится стартовый набор. Порт из `glyphstroke/recognizer.py`, пороги и цены
/// совпадают с версией для Linux, иначе один и тот же файл жеста вёл бы себя
/// на двух машинах по-разному.
public enum DirectionCode {
    /// Экранная система координат: X вправо, Y вниз.
    public static let names = ["R", "DR", "D", "DL", "L", "UL", "U", "UR"]

    /// Лишний октант рядом с уже принятым — дрожание руки, почти бесплатно.
    static let wobbleCost = 0.35
    /// Скачок через октант означает, что нарисовали другую фигуру.
    static let extraCost = 1.0

    static func octant(dx: Double, dy: Double) -> String {
        var angle = atan2(dy, dx) * 180.0 / .pi
        angle = angle.truncatingRemainder(dividingBy: 360.0)
        if angle < 0 { angle += 360.0 }
        let index = Int(((angle + 22.5).truncatingRemainder(dividingBy: 360.0)) / 45.0)
        return names[index % 8]
    }

    /// Разложить росчерк в строку октантов.
    ///
    /// Шаг дискретизации берётся от размера самого росчерка, поэтому код не
    /// зависит от того, крупно или мелко нарисован жест.
    public static func of(_ points: [Point], stepRatio: Double = 0.16, minStepPx: Double = 12.0) -> String {
        let pts = Geometry.dedupe(points)
        guard pts.count >= 2 else { return "" }

        let total = Geometry.pathLength(pts)
        let box = Geometry.boundingBox(pts)
        let step = max(minStepPx, stepRatio * max(hypot(box.width, box.height), total * 0.5))

        var raw: [String] = []
        var anchor = pts[0]
        for p in pts.dropFirst() where anchor.distance(to: p) >= step {
            raw.append(octant(dx: p.x - anchor.x, dy: p.y - anchor.y))
            anchor = p
        }
        if raw.isEmpty {
            let first = pts[0], last = pts[pts.count - 1]
            raw.append(octant(dx: last.x - first.x, dy: last.y - first.y))
        }

        // Схлопываем повторы, попутно считая длину каждой серии.
        var runs: [(direction: String, count: Int)] = []
        for d in raw {
            if let last = runs.last, last.direction == d {
                runs[runs.count - 1].count += 1
            } else {
                runs.append((d, 1))
            }
        }

        // Выкидываем одиночные октанты-«скругления» между двумя соседними.
        var cleaned: [(direction: String, count: Int)] = []
        for (i, run) in runs.enumerated() {
            if run.count == 1, i > 0, i < runs.count - 1 {
                let prev = runs[i - 1].direction, next = runs[i + 1].direction
                if adjacent(prev, run.direction) && adjacent(run.direction, next) {
                    continue
                }
            }
            if let last = cleaned.last, last.direction == run.direction {
                cleaned[cleaned.count - 1].count += run.count
            } else {
                cleaned.append(run)
            }
        }
        // Ключевой путь к элементу кортежа Swift не умеет — только замыкание.
        return cleaned.map { $0.direction }.joined(separator: "-")
    }

    /// Насколько далеко друг от друга два направления, в октантах (0…4).
    public static func distance(_ a: String, _ b: String) -> Int {
        guard let i = names.firstIndex(of: a), let j = names.firstIndex(of: b) else { return 4 }
        let forward = (i - j + 8) % 8
        let backward = (j - i + 8) % 8
        return min(forward, backward)
    }

    static func adjacent(_ a: String, _ b: String) -> Bool {
        distance(a, b) == 1
    }

    static func skipCost(_ sequence: [String], _ index: Int) -> Double {
        var neighbours: [String] = []
        if index > 0 { neighbours.append(sequence[index - 1]) }
        if index < sequence.count - 1 { neighbours.append(sequence[index + 1]) }
        return neighbours.contains(where: { adjacent(sequence[index], $0) }) ? wobbleCost : extraCost
    }

    /// Насколько нарисованный код похож на заданный, от 0 до 1.
    ///
    /// Строгое посимвольное сравнение бракует нормальные росчерки: рука уводит
    /// хвост линии, и вместо `L` получается `L-DL`. Поэтому считаем расстояние
    /// редактирования, где замена стоит тем дороже, чем дальше направления друг
    /// от друга, а лишний соседний октант почти бесплатен.
    public static func similarity(drawn: String, target: String) -> Double {
        guard !drawn.isEmpty, !target.isEmpty else { return 0 }
        let a = drawn.split(separator: "-").map(String.init).filter { names.contains($0) }
        let b = target.split(separator: "-").map(String.init).filter { names.contains($0) }
        guard !a.isEmpty, !b.isEmpty else { return 0 }
        if a == b { return 1 }

        let rows = a.count, cols = b.count
        var cost = Array(repeating: Array(repeating: 0.0, count: cols + 1), count: rows + 1)
        for i in 1...rows {
            cost[i][0] = cost[i - 1][0] + skipCost(a, i - 1)
        }
        for j in 1...cols {
            cost[0][j] = cost[0][j - 1] + skipCost(b, j - 1)
        }
        for i in 1...rows {
            for j in 1...cols {
                let substitute = cost[i - 1][j - 1] + Double(distance(a[i - 1], b[j - 1])) / 4.0
                let drop = cost[i - 1][j] + skipCost(a, i - 1)
                let add = cost[i][j - 1] + skipCost(b, j - 1)
                cost[i][j] = min(substitute, min(drop, add))
            }
        }
        return max(0, 1.0 - cost[rows][cols] / Double(max(rows, cols)))
    }
}
