namespace Glyphstroke.Core;

/// <summary>
/// Код направлений: росчерк как строка октантов вида <c>D-R</c> — «вниз,
/// потом вправо».
/// </summary>
/// <remarks>
/// Таким кодом фигуру можно описать текстом, ничего не рисуя, — на этом держится
/// стартовый набор. Порт из <c>glyphstroke/recognizer.py</c>: пороги и цены
/// совпадают с версиями для Linux и macOS, иначе один и тот же файл жеста вёл
/// бы себя на разных машинах по-разному.
/// </remarks>
public static class DirectionCode
{
    /// <summary>Экранная система координат: X вправо, Y вниз.</summary>
    public static readonly string[] Names = { "R", "DR", "D", "DL", "L", "UL", "U", "UR" };

    /// <summary>Лишний октант рядом с уже принятым — дрожание руки, почти бесплатно.</summary>
    private const double WobbleCost = 0.35;

    /// <summary>Скачок через октант означает, что нарисовали другую фигуру.</summary>
    private const double ExtraCost = 1.0;

    public static string Octant(double dx, double dy)
    {
        double angle = Math.Atan2(dy, dx) * 180.0 / Math.PI % 360.0;
        if (angle < 0)
        {
            angle += 360.0;
        }
        int index = (int)((angle + 22.5) % 360.0 / 45.0);
        return Names[index % 8];
    }

    /// <summary>Разложить росчерк в строку октантов.</summary>
    /// <remarks>
    /// Шаг дискретизации берётся от размера самого росчерка, поэтому код не
    /// зависит от того, крупно или мелко нарисован жест.
    /// </remarks>
    public static string Of(IReadOnlyList<Point> points, double stepRatio = 0.16, double minStepPx = 12.0)
    {
        var pts = Geometry.Dedupe(points);
        if (pts.Count < 2)
        {
            return string.Empty;
        }

        double total = Geometry.PathLength(pts);
        var box = Geometry.BoundingBox(pts);
        double diagonal = Math.Sqrt(box.Width * box.Width + box.Height * box.Height);
        double step = Math.Max(minStepPx, stepRatio * Math.Max(diagonal, total * 0.5));

        var raw = new List<string>();
        var anchor = pts[0];
        for (int i = 1; i < pts.Count; i++)
        {
            var p = pts[i];
            if (anchor.DistanceTo(p) >= step)
            {
                raw.Add(Octant(p.X - anchor.X, p.Y - anchor.Y));
                anchor = p;
            }
        }
        if (raw.Count == 0)
        {
            raw.Add(Octant(pts[^1].X - pts[0].X, pts[^1].Y - pts[0].Y));
        }

        // Схлопываем повторы, попутно считая длину каждой серии.
        var runs = new List<(string Direction, int Count)>();
        foreach (var direction in raw)
        {
            if (runs.Count > 0 && runs[^1].Direction == direction)
            {
                runs[^1] = (direction, runs[^1].Count + 1);
            }
            else
            {
                runs.Add((direction, 1));
            }
        }

        // Выкидываем одиночные октанты-«скругления» между двумя соседними.
        var cleaned = new List<(string Direction, int Count)>();
        for (int i = 0; i < runs.Count; i++)
        {
            var run = runs[i];
            if (run.Count == 1 && i > 0 && i < runs.Count - 1
                && Adjacent(runs[i - 1].Direction, run.Direction)
                && Adjacent(run.Direction, runs[i + 1].Direction))
            {
                continue;
            }
            if (cleaned.Count > 0 && cleaned[^1].Direction == run.Direction)
            {
                cleaned[^1] = (run.Direction, cleaned[^1].Count + run.Count);
            }
            else
            {
                cleaned.Add(run);
            }
        }
        return string.Join("-", cleaned.Select(item => item.Direction));
    }

    /// <summary>Насколько далеко друг от друга два направления, в октантах (0…4).</summary>
    public static int Distance(string a, string b)
    {
        int i = Array.IndexOf(Names, a), j = Array.IndexOf(Names, b);
        if (i < 0 || j < 0)
        {
            return 4;
        }
        return Math.Min((i - j + 8) % 8, (j - i + 8) % 8);
    }

    private static bool Adjacent(string a, string b) => Distance(a, b) == 1;

    private static double SkipCost(IReadOnlyList<string> sequence, int index)
    {
        bool nearPrevious = index > 0 && Adjacent(sequence[index], sequence[index - 1]);
        bool nearNext = index < sequence.Count - 1 && Adjacent(sequence[index], sequence[index + 1]);
        return nearPrevious || nearNext ? WobbleCost : ExtraCost;
    }

    /// <summary>Насколько нарисованный код похож на заданный, от 0 до 1.</summary>
    /// <remarks>
    /// Строгое посимвольное сравнение бракует нормальные росчерки: рука уводит
    /// хвост линии, и вместо <c>L</c> получается <c>L-DL</c>. Поэтому считаем
    /// расстояние редактирования, где замена стоит тем дороже, чем дальше
    /// направления друг от друга, а лишний соседний октант почти бесплатен.
    /// </remarks>
    public static double Similarity(string drawn, string target)
    {
        if (string.IsNullOrEmpty(drawn) || string.IsNullOrEmpty(target))
        {
            return 0;
        }
        var a = drawn.Split('-').Where(part => Names.Contains(part)).ToList();
        var b = target.Split('-').Where(part => Names.Contains(part)).ToList();
        if (a.Count == 0 || b.Count == 0)
        {
            return 0;
        }
        if (a.SequenceEqual(b))
        {
            return 1;
        }

        int rows = a.Count, cols = b.Count;
        var cost = new double[rows + 1, cols + 1];
        for (int i = 1; i <= rows; i++)
        {
            cost[i, 0] = cost[i - 1, 0] + SkipCost(a, i - 1);
        }
        for (int j = 1; j <= cols; j++)
        {
            cost[0, j] = cost[0, j - 1] + SkipCost(b, j - 1);
        }
        for (int i = 1; i <= rows; i++)
        {
            for (int j = 1; j <= cols; j++)
            {
                double substitute = cost[i - 1, j - 1] + Distance(a[i - 1], b[j - 1]) / 4.0;
                double drop = cost[i - 1, j] + SkipCost(a, i - 1);
                double add = cost[i, j - 1] + SkipCost(b, j - 1);
                cost[i, j] = Math.Min(substitute, Math.Min(drop, add));
            }
        }
        return Math.Max(0, 1.0 - cost[rows, cols] / Math.Max(rows, cols));
    }
}
