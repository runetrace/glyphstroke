namespace Glyphstroke.Core;

/// <summary>Жест, каким его видит распознаватель: фигура без действий.</summary>
public sealed class GestureDefinition
{
    public string Name { get; }
    public IReadOnlyList<IReadOnlyList<Point>> Templates { get; }
    public IReadOnlyList<string> Directions { get; }
    /// <summary>Допуск поворота в радианах.</summary>
    public double RotationTolerance { get; }

    /// <summary>
    /// Образцы, приведённые к сравнимому виду. Считается один раз: нормализация
    /// 64 точек на каждый образец при каждом росчерке — заметная работа впустую.
    /// </summary>
    public IReadOnlyList<IReadOnlyList<Point>> NormalizedTemplates { get; }

    public GestureDefinition(string name,
        IReadOnlyList<IReadOnlyList<Point>>? templates = null,
        IReadOnlyList<string>? directions = null,
        double rotationTolerance = 20.0 * Math.PI / 180.0)
    {
        Name = name;
        Templates = templates ?? Array.Empty<IReadOnlyList<Point>>();
        Directions = directions ?? Array.Empty<string>();
        RotationTolerance = rotationTolerance;
        NormalizedTemplates = Templates
            .Where(template => template.Count >= 2)
            .Select(template => (IReadOnlyList<Point>)Geometry.Normalize(template))
            .ToList();
    }
}

/// <summary>Что вышло из росчерка.</summary>
public sealed record Match(string? Name, double Score, string Code,
                           string? RunnerUp = null, double RunnerUpScore = 0);

/// <summary>Сопоставление росчерка с набором жестов.</summary>
/// <remarks>
/// Два независимых способа на одном списке точек: шаблоны (алгоритм $1 без
/// поворота к главной оси) и код направлений. Берётся лучший, а дальше решают
/// два порога: минимальная оценка и отрыв от второго места. Отрыв важнее, чем
/// кажется: два похожих жеста лучше не выполнить вовсе, чем выполнить наугад.
/// </remarks>
public sealed class Recognizer
{
    private readonly IReadOnlyList<GestureDefinition> _gestures;
    private readonly double _minScore;
    private readonly double _minMargin;

    public Recognizer(IReadOnlyList<GestureDefinition> gestures,
                      double minScore = 0.80, double minMargin = 0.05)
    {
        _gestures = gestures;
        _minScore = minScore;
        _minMargin = minMargin;
    }

    public List<(string Name, double Score)> ScoreAll(IReadOnlyList<Point> points)
    {
        string code = DirectionCode.Of(points);
        var candidate = Geometry.Normalize(points);
        var scored = new List<(string Name, double Score)>();

        foreach (var gesture in _gestures)
        {
            double best = 0;
            foreach (var wanted in gesture.Directions)
            {
                best = Math.Max(best, DirectionCode.Similarity(code, wanted));
            }
            foreach (var template in gesture.NormalizedTemplates)
            {
                double d = Geometry.DistanceAtBestAngle(candidate, template, gesture.RotationTolerance);
                best = Math.Max(best, 1.0 - d / Geometry.HalfDiagonal);
            }
            if (best > 0)
            {
                scored.Add((gesture.Name, best));
            }
        }
        scored.Sort((left, right) => right.Score.CompareTo(left.Score));
        return scored;
    }

    public Match Recognize(IReadOnlyList<Point> points)
    {
        string code = DirectionCode.Of(points);
        var scored = ScoreAll(points);
        if (scored.Count == 0)
        {
            return new Match(null, 0, code);
        }

        var first = scored[0];
        string? secondName = scored.Count > 1 ? scored[1].Name : null;
        double secondScore = scored.Count > 1 ? scored[1].Score : 0;

        if (first.Score < _minScore)
        {
            // Ничего не подошло: показываем самого близкого, чтобы было видно,
            // чего не хватило.
            return new Match(null, first.Score, code, first.Name, first.Score);
        }
        if (first.Score - secondScore < _minMargin)
        {
            return new Match(null, first.Score, code, secondName, secondScore);
        }
        return new Match(first.Name, first.Score, code, secondName, secondScore);
    }
}
