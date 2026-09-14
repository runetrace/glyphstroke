namespace Glyphstroke.Core;

/// <summary>Точка росчерка: X вправо, Y вниз — как на экране.</summary>
/// <remarks>
/// Своя структура, а не System.Drawing.PointF: ядро не зависит от графических
/// библиотек, и его проверки гоняются где угодно.
/// </remarks>
public readonly record struct Point(double X, double Y)
{
    public double DistanceTo(Point other) => Math.Sqrt(
        (other.X - X) * (other.X - X) + (other.Y - Y) * (other.Y - Y));
}

/// <summary>
/// Геометрия росчерка: всё, что нужно алгоритму $1 Unistroke.
/// </summary>
/// <remarks>
/// Перенесено из версии для Linux (<c>glyphstroke/recognizer.py</c>) число в число.
/// Это не педантизм: файлы жестов у трёх версий общие, и разъехавшиеся пороги
/// означали бы, что один и тот же жест на двух машинах ведёт себя по-разному,
/// причём молча.
/// </remarks>
public static class Geometry
{
    /// <summary>Сколько точек остаётся после выравнивания по длине пути.</summary>
    public const int NumPoints = 64;

    /// <summary>Сторона квадрата, в который вписывается росчерк.</summary>
    public const double SquareSize = 250.0;

    public static readonly double HalfDiagonal = 0.5 * Math.Sqrt(SquareSize * SquareSize * 2);

    /// <summary>Золотое сечение — для поиска лучшего угла.</summary>
    public static readonly double Phi = 0.5 * (-1.0 + Math.Sqrt(5.0));

    /// <summary>
    /// Росчерк вытянутее, чем 1:4, сжимаем равномерно: иначе прямая линия
    /// растянулась бы в квадрат и потеряла форму.
    /// </summary>
    public const double ThinRatio = 0.25;

    public static double PathLength(IReadOnlyList<Point> points)
    {
        double total = 0;
        for (int i = 1; i < points.Count; i++)
        {
            total += points[i - 1].DistanceTo(points[i]);
        }
        return total;
    }

    public static List<Point> Dedupe(IReadOnlyList<Point> points, double eps = 1e-9)
    {
        var result = new List<Point>(points.Count);
        foreach (var point in points)
        {
            if (result.Count == 0 || result[^1].DistanceTo(point) > eps)
            {
                result.Add(point);
            }
        }
        return result;
    }

    /// <summary>Разложить росчерк на <paramref name="n"/> равноудалённых точек.</summary>
    public static List<Point> Resample(IReadOnlyList<Point> points, int n = NumPoints)
    {
        var pts = Dedupe(points);
        if (pts.Count < 2)
        {
            var single = pts.Count == 1 ? pts[0] : new Point(0, 0);
            return Enumerable.Repeat(single, n).ToList();
        }

        double interval = PathLength(pts) / (n - 1);
        if (interval <= 0)
        {
            return Enumerable.Repeat(pts[0], n).ToList();
        }

        var output = new List<Point> { pts[0] };
        double accumulated = 0;
        int i = 1;
        while (i < pts.Count)
        {
            double d = pts[i - 1].DistanceTo(pts[i]);
            if (accumulated + d >= interval)
            {
                double t = (interval - accumulated) / d;
                var next = new Point(
                    pts[i - 1].X + t * (pts[i].X - pts[i - 1].X),
                    pts[i - 1].Y + t * (pts[i].Y - pts[i - 1].Y));
                output.Add(next);
                // Точка вставляется в исходный список: следующий отрезок
                // отмеряется уже от неё, иначе шаг «уплывает».
                pts.Insert(i, next);
                accumulated = 0;
            }
            else
            {
                accumulated += d;
            }
            i++;
        }

        // Хвост добираем из-за накопленной ошибки вещественных чисел.
        while (output.Count < n)
        {
            output.Add(pts[^1]);
        }
        return output.Take(n).ToList();
    }

    public static Point Centroid(IReadOnlyList<Point> points)
    {
        if (points.Count == 0)
        {
            return new Point(0, 0);
        }
        double x = 0, y = 0;
        foreach (var point in points)
        {
            x += point.X;
            y += point.Y;
        }
        return new Point(x / points.Count, y / points.Count);
    }

    public static (double X, double Y, double Width, double Height) BoundingBox(IReadOnlyList<Point> points)
    {
        if (points.Count == 0)
        {
            return (0, 0, 0, 0);
        }
        double minX = points.Min(p => p.X), maxX = points.Max(p => p.X);
        double minY = points.Min(p => p.Y), maxY = points.Max(p => p.Y);
        return (minX, minY, maxX - minX, maxY - minY);
    }

    public static List<Point> RotateBy(IReadOnlyList<Point> points, double radians)
    {
        var c = Centroid(points);
        double cos = Math.Cos(radians), sin = Math.Sin(radians);
        return points.Select(p => new Point(
            (p.X - c.X) * cos - (p.Y - c.Y) * sin + c.X,
            (p.X - c.X) * sin + (p.Y - c.Y) * cos + c.Y)).ToList();
    }

    public static List<Point> ScaleToSquare(IReadOnlyList<Point> points, double size = SquareSize)
    {
        var box = BoundingBox(points);
        if (box.Width <= 0 && box.Height <= 0)
        {
            return points.ToList();
        }

        double longest = Math.Max(box.Width, box.Height);
        bool thin = longest > 0 ? Math.Min(box.Width, box.Height) / longest < ThinRatio : true;
        if (thin)
        {
            double k = size / longest;
            return points.Select(p => new Point(p.X * k, p.Y * k)).ToList();
        }
        return points.Select(p => new Point(p.X * size / box.Width, p.Y * size / box.Height)).ToList();
    }

    public static List<Point> TranslateToOrigin(IReadOnlyList<Point> points)
    {
        var c = Centroid(points);
        return points.Select(p => new Point(p.X - c.X, p.Y - c.Y)).ToList();
    }

    /// <summary>Привести росчерк к виду, пригодному для сравнения с шаблоном.</summary>
    public static List<Point> Normalize(IReadOnlyList<Point> points, int n = NumPoints) =>
        TranslateToOrigin(ScaleToSquare(Resample(points, n)));

    public static double PathDistance(IReadOnlyList<Point> a, IReadOnlyList<Point> b)
    {
        int count = Math.Min(a.Count, b.Count);
        if (count == 0)
        {
            return double.PositiveInfinity;
        }
        double total = 0;
        for (int i = 0; i < count; i++)
        {
            total += a[i].DistanceTo(b[i]);
        }
        return total / a.Count;
    }

    public static double DistanceAtAngle(IReadOnlyList<Point> points, IReadOnlyList<Point> template, double angle) =>
        PathDistance(RotateBy(points, angle), template);

    /// <summary>
    /// Поиск золотым сечением по углу в пределах ±<paramref name="tolerance"/>.
    /// </summary>
    /// <remarks>
    /// Допуск маленький (по умолчанию 20°): он гасит дрожание руки, но не даёт
    /// спутать жест с его же поворотом на 90°.
    /// </remarks>
    public static double DistanceAtBestAngle(IReadOnlyList<Point> points, IReadOnlyList<Point> template,
        double tolerance, double precision = 2.0 * Math.PI / 180.0)
    {
        double straight = DistanceAtAngle(points, template, 0);
        if (tolerance <= 0)
        {
            return straight;
        }

        double lo = -tolerance, hi = tolerance;
        double x1 = Phi * lo + (1.0 - Phi) * hi;
        double f1 = DistanceAtAngle(points, template, x1);
        double x2 = (1.0 - Phi) * lo + Phi * hi;
        double f2 = DistanceAtAngle(points, template, x2);

        while (Math.Abs(hi - lo) > precision)
        {
            if (f1 < f2)
            {
                hi = x2;
                x2 = x1;
                f2 = f1;
                x1 = Phi * lo + (1.0 - Phi) * hi;
                f1 = DistanceAtAngle(points, template, x1);
            }
            else
            {
                lo = x1;
                x1 = x2;
                f1 = f2;
                x2 = (1.0 - Phi) * lo + Phi * hi;
                f2 = DistanceAtAngle(points, template, x2);
            }
        }
        // Угол 0 проверяем отдельно: поиск в него не попадает и слегка портит
        // оценку даже при точном совпадении росчерка с шаблоном.
        return Math.Min(straight, Math.Min(f1, f2));
    }
}
