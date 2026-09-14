import Foundation

/// Жест, каким его видит распознаватель: фигура без действий.
public struct GestureDefinition {
    public var name: String
    /// Нарисованные образцы: сравниваются алгоритмом $1.
    public var templates: [[Point]]
    /// Коды направлений вида `D-R`.
    public var directions: [String]
    /// Допуск поворота в радианах.
    public var rotationTolerance: Double

    /// Образцы, приведённые к сравнимому виду. Считается один раз: нормализация
    /// 64 точек на каждый образец при каждом росчерке — заметная работа впустую.
    public let normalizedTemplates: [[Point]]

    public init(name: String, templates: [[Point]] = [], directions: [String] = [],
                rotationTolerance: Double = 20.0 * .pi / 180.0) {
        self.name = name
        self.templates = templates
        self.directions = directions
        self.rotationTolerance = rotationTolerance
        self.normalizedTemplates = templates.filter { $0.count >= 2 }.map { Geometry.normalize($0) }
    }
}

/// Что вышло из росчерка.
public struct Match {
    /// Имя опознанного жеста; `nil` — не опознан.
    public var name: String?
    public var score: Double
    /// Код направлений самого росчерка — его показывает «glyphstroke test» и журнал.
    public var code: String
    /// Кто был вторым: по нему видно, чего не хватило.
    public var runnerUp: String?
    public var runnerUpScore: Double

    public init(name: String?, score: Double, code: String,
                runnerUp: String? = nil, runnerUpScore: Double = 0) {
        self.name = name
        self.score = score
        self.code = code
        self.runnerUp = runnerUp
        self.runnerUpScore = runnerUpScore
    }
}

/// Сопоставление росчерка с набором жестов.
///
/// Два независимых способа на одном и том же списке точек: шаблоны ($1
/// Unistroke без поворота к главной оси) и код направлений. Берётся лучший из
/// них, а дальше решают два порога: минимальная оценка и отрыв от второго
/// места. Отрыв важнее, чем кажется: два похожих жеста лучше не выполнить
/// вовсе, чем выполнить наугад.
public struct Recognizer {
    public var gestures: [GestureDefinition]
    public var minScore: Double
    public var minMargin: Double

    public init(gestures: [GestureDefinition], minScore: Double = 0.80, minMargin: Double = 0.05) {
        self.gestures = gestures
        self.minScore = minScore
        self.minMargin = minMargin
    }

    public func scoreAll(_ points: [Point]) -> [(name: String, score: Double)] {
        let code = DirectionCode.of(points)
        let candidate = Geometry.normalize(points)
        var scored: [(name: String, score: Double)] = []

        for gesture in gestures {
            var best = 0.0
            for wanted in gesture.directions {
                best = max(best, DirectionCode.similarity(drawn: code, target: wanted))
            }
            for template in gesture.normalizedTemplates {
                let d = Geometry.distanceAtBestAngle(candidate, template: template,
                                                     tolerance: gesture.rotationTolerance)
                best = max(best, 1.0 - d / Geometry.halfDiagonal)
            }
            if best > 0 {
                scored.append((gesture.name, best))
            }
        }
        scored.sort { $0.score > $1.score }
        return scored
    }

    public func recognize(_ points: [Point]) -> Match {
        let code = DirectionCode.of(points)
        let scored = scoreAll(points)
        guard let first = scored.first else {
            return Match(name: nil, score: 0, code: code)
        }
        let secondName: String? = scored.count > 1 ? scored[1].name : nil
        let secondScore: Double = scored.count > 1 ? scored[1].score : 0

        if first.score < minScore {
            // Ничего не подошло: показываем самого близкого, чтобы было видно,
            // чего не хватило.
            return Match(name: nil, score: first.score, code: code,
                         runnerUp: first.name, runnerUpScore: first.score)
        }
        if (first.score - secondScore) < minMargin {
            return Match(name: nil, score: first.score, code: code,
                         runnerUp: secondName, runnerUpScore: secondScore)
        }
        return Match(name: first.name, score: first.score, code: code,
                     runnerUp: secondName, runnerUpScore: secondScore)
    }
}
