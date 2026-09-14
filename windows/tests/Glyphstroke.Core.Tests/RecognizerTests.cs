using Glyphstroke.Core;
using Xunit;

namespace Glyphstroke.Core.Tests;

/// <summary>Проверки распознавания — те же, что в версиях для Linux и macOS.</summary>
/// <remarks>
/// Смысл не в том, чтобы проверить арифметику ещё раз, а в том, чтобы
/// зафиксировать совпадение трёх портов: файл жеста, нарисованный на одной
/// машине, обязан срабатывать на другой. Разъедутся пороги — разъедутся и
/// жесты, причём молча. Ожидаемые числа сверены с рабочей версией для Linux.
/// </remarks>
public class RecognizerTests
{
    private static List<Point> Line(double x0, double y0, double x1, double y1, int count = 40)
    {
        var points = new List<Point>();
        for (int i = 0; i < count; i++)
        {
            double t = (double)i / (count - 1);
            points.Add(new Point(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t));
        }
        return points;
    }

    /// <summary>Дрожание руки: повторяемое, без случайных чисел — иначе тест то
    /// падает, то нет, и верить ему нельзя.</summary>
    private static List<Point> Shaky(List<Point> points, double amount = 1.5) =>
        points.Select((point, index) => new Point(
            point.X + amount * Math.Sin(index * 1.7),
            point.Y + amount * Math.Cos(index * 2.3))).ToList();

    // --- геометрия ---

    [Fact]
    public void ResampleGivesUniformSpacing()
    {
        var points = Geometry.Resample(Line(0, 0, 300, 0), 64);
        Assert.Equal(64, points.Count);
        var gaps = new List<double>();
        for (int i = 1; i < points.Count; i++)
        {
            gaps.Add(points[i - 1].DistanceTo(points[i]));
        }
        Assert.True(gaps.Max() - gaps.Min() < 1e-6);
    }

    [Fact]
    public void PathLengthOfCorner()
    {
        var stroke = Line(0, 0, 0, 100).Concat(Line(0, 100, 100, 100)).ToList();
        Assert.InRange(Geometry.PathLength(stroke), 199, 201);
    }

    // --- коды направлений ---

    [Theory]
    [InlineData(200, 0, "R")]
    [InlineData(-200, 0, "L")]
    [InlineData(0, 200, "D")]
    [InlineData(0, -200, "U")]
    [InlineData(150, 150, "DR")]
    [InlineData(-150, 150, "DL")]
    public void StraightStrokesGiveOneOctant(double x, double y, string expected) =>
        Assert.Equal(expected, DirectionCode.Of(Line(0, 0, x, y)));

    [Fact]
    public void CornerGivesTwoOctants()
    {
        var stroke = Line(0, 0, 0, 200).Concat(Line(0, 200, 200, 200)).ToList();
        Assert.Equal("D-R", DirectionCode.Of(stroke));
    }

    [Fact]
    public void CodeDoesNotDependOnSize()
    {
        var small = DirectionCode.Of(Line(0, 0, 0, 60).Concat(Line(0, 60, 60, 60)).ToList());
        var large = DirectionCode.Of(Line(0, 0, 0, 600).Concat(Line(0, 600, 600, 600)).ToList());
        Assert.Equal(small, large);
    }

    [Fact]
    public void EmptyStrokeHasNoCode()
    {
        Assert.Equal(string.Empty, DirectionCode.Of(new List<Point>()));
        Assert.Equal(string.Empty, DirectionCode.Of(new List<Point> { new(10, 10) }));
    }

    [Fact]
    public void OctantDistanceWrapsAround()
    {
        Assert.Equal(0, DirectionCode.Distance("R", "R"));
        Assert.Equal(1, DirectionCode.Distance("R", "UR"));
        Assert.Equal(4, DirectionCode.Distance("R", "L"));
        Assert.Equal(2, DirectionCode.Distance("UR", "DR"));
    }

    [Fact]
    public void ShakyHandStillMatches()
    {
        // Хвост линии уводит вбок — это по-прежнему тот же жест.
        Assert.True(DirectionCode.Similarity("L-DL", "L") > 0.8);
        Assert.True(DirectionCode.Similarity("D-DR-R", "D-R") > 0.8);
    }

    [Fact]
    public void DifferentShapesDoNotMatch()
    {
        Assert.True(DirectionCode.Similarity("L", "R") < 0.5);
        Assert.True(DirectionCode.Similarity("D-R", "U-L") < 0.5);
    }

    // --- шаблоны ---

    [Fact]
    public void TemplateMatchesItself()
    {
        var stroke = Line(0, 0, 0, 200).Concat(Line(0, 200, 200, 200)).ToList();
        double distance = Geometry.DistanceAtBestAngle(
            Geometry.Normalize(stroke), Geometry.Normalize(stroke), 20.0 * Math.PI / 180.0);
        Assert.True(distance < 1e-6);
    }

    [Fact]
    public void TemplateToleratesSizeAndShift()
    {
        var template = Geometry.Normalize(Line(0, 0, 0, 200).Concat(Line(0, 200, 200, 200)).ToList());
        var drawn = Geometry.Normalize(Line(500, 500, 500, 600).Concat(Line(500, 600, 600, 600)).ToList());
        double distance = Geometry.DistanceAtBestAngle(drawn, template, 20.0 * Math.PI / 180.0);
        // Та же фигура вдвое мельче и в другом углу экрана — это тот же жест.
        Assert.True(1.0 - distance / Geometry.HalfDiagonal > 0.99);
    }

    // --- сопоставление целиком ---

    private static Recognizer Sample() => new(new List<GestureDefinition>
    {
        new("Назад", directions: new[] { "L" }),
        new("Вперёд", directions: new[] { "R" }),
        new("Новая вкладка", directions: new[] { "U" }),
        new("Свернуть окно", directions: new[] { "L-D" }),
    });

    [Fact]
    public void StraightStrokeFiresItsGesture()
    {
        var match = Sample().Recognize(Line(0, 0, -200, 0));
        Assert.Equal("Назад", match.Name);
        Assert.Equal("L", match.Code);
    }

    [Fact]
    public void WobblyStrokeFiresTheIntendedGesture() =>
        Assert.Equal("Назад", Sample().Recognize(Shaky(Line(0, 0, -220, 6))).Name);

    [Fact]
    public void UnknownStrokeReturnsNothing()
    {
        var match = Sample().Recognize(Line(0, 0, 150, 150));
        Assert.Null(match.Name);
        Assert.Equal("DR", match.Code);
        Assert.NotNull(match.RunnerUp);      // человеку надо показать, чего не хватило
    }

    [Fact]
    public void AmbiguousStrokeFiresNothing()
    {
        // Два жеста с одинаковой фигурой: сработать не должен ни один — наугад
        // выполнять чужое действие хуже, чем не выполнить ничего.
        var engine = new Recognizer(new List<GestureDefinition>
        {
            new("Первый", directions: new[] { "L" }),
            new("Второй", directions: new[] { "L" }),
        });
        var match = engine.Recognize(Line(0, 0, -200, 0));
        Assert.Null(match.Name);
        Assert.NotNull(match.RunnerUp);
    }
}
