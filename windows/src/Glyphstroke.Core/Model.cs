using System.Text.RegularExpressions;

namespace Glyphstroke.Core;

/// <summary>Действие жеста: что выполнить, когда росчерк опознан.</summary>
/// <remarks>
/// Набор типов общий с версиями для Linux и macOS — файлы жестов переносятся
/// между машинами как есть. Что именно умеет каждая система, решает исполнитель.
/// </remarks>
public sealed class GestureAction
{
    /// <summary>standard | command | app | keys | text | button | scroll | window | delay | none</summary>
    public string Type { get; set; } = "none";
    public string Value { get; set; } = string.Empty;

    public GestureAction() { }

    public GestureAction(string type, string value = "")
    {
        Type = type;
        Value = value;
    }
}

/// <summary>Пункт меню под жестом: название и свои действия.</summary>
public sealed class MenuItem
{
    public string Name { get; set; } = string.Empty;
    public List<GestureAction> Actions { get; set; } = new();
}

/// <summary>Жест целиком: фигура, условия и что делать.</summary>
public sealed class Gesture
{
    public string Name { get; set; } = "gesture";
    public bool Enabled { get; set; } = true;

    /// <summary>Если задано — жест опознаётся событием мыши, росчерк не рисуется.</summary>
    public string Event { get; set; } = string.Empty;

    public List<string> Directions { get; set; } = new();
    public List<List<Point>> Templates { get; set; } = new();

    /// <summary>Фильтр по программам; пусто — жест работает везде.</summary>
    public List<string> Apps { get; set; } = new();

    /// <summary>Допуск поворота в градусах — в файле он хранится именно так.</summary>
    public double RotationTolerance { get; set; } = 20.0;

    public List<GestureAction> Actions { get; set; } = new();
    public List<MenuItem> Menu { get; set; } = new();
    public string Description { get; set; } = string.Empty;

    /// <summary>Файл, из которого жест прочитан.</summary>
    public string? FilePath { get; set; }

    public GestureDefinition ToDefinition() => new(
        Name,
        Templates.Select(template => (IReadOnlyList<Point>)template).ToList(),
        Directions,
        RotationTolerance * Math.PI / 180.0);

    /// <summary>Подходит ли жест программе, которая сейчас впереди.</summary>
    /// <remarks>
    /// Жест с фильтром не должен срабатывать вслепую: не знаем программу —
    /// считаем, что не подходит.
    /// </remarks>
    public bool Matches(string? app)
    {
        if (Apps.Count == 0)
        {
            return true;
        }
        if (string.IsNullOrEmpty(app))
        {
            return false;
        }
        return Apps.Any(pattern => AppMatches(pattern, app));
    }

    /// <summary>Пометка «это точное имя программы, а не выражение».</summary>
    public const string ClassPrefix = "class:";

    /// <summary>
    /// Сверка программы с образцом — так же, как на Linux и macOS.
    /// </summary>
    /// <remarks>
    /// Образец бывает двух видов. С пометкой <c>class:</c> — точное имя
    /// программы: на Linux класс окна, на маке идентификатор пакета, здесь имя
    /// исполняемого файла («class:chrome.exe»). Без пометки — регулярное
    /// выражение, которое ищется в строке «программа | заголовок окна».
    /// Опечатка в выражении не должна ронять разбор росчерка, поэтому негодное
    /// выражение просто не совпадает.
    /// </remarks>
    public static bool AppMatches(string pattern, string app)
    {
        string trimmed = (pattern ?? string.Empty).Trim();
        if (trimmed.Length == 0)
        {
            return false;
        }

        if (trimmed.StartsWith(ClassPrefix, StringComparison.OrdinalIgnoreCase))
        {
            string wanted = trimmed[ClassPrefix.Length..].Trim();
            return string.Equals(wanted, WindowClass(app), StringComparison.OrdinalIgnoreCase);
        }

        try
        {
            return Regex.IsMatch(app, trimmed, RegexOptions.IgnoreCase);
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    /// <summary><c>"chrome.exe | Заголовок"</c> → <c>"chrome.exe"</c>.</summary>
    public static string WindowClass(string app)
    {
        int separator = app.IndexOf(" | ", StringComparison.Ordinal);
        return (separator >= 0 ? app[..separator] : app).Trim();
    }
}

/// <summary>Вид следа за курсором.</summary>
public sealed class OverlaySettings
{
    public bool Enabled { get; set; } = true;
    public string Color { get; set; } = "#4da3ff";
    public int Width { get; set; } = 4;
    public double Opacity { get; set; } = 0.9;
    public int FadeMs { get; set; } = 220;
}

/// <summary>Настройки программы.</summary>
/// <remarks>
/// Имена полей в файле те же, что у версий для Linux и macOS: settings.yaml
/// общий. Ключи, которых на этой системе нет, читаются и сохраняются как есть —
/// иначе перенос настроек туда-обратно затирал бы их молча.
/// </remarks>
public sealed class Settings
{
    public string Language { get; set; } = "auto";
    /// <summary>Тема окон: system — как в системе, иначе light/dark.</summary>
    public string Theme { get; set; } = "system";
    public string ActiveProfile { get; set; } = string.Empty;

    /// <summary>Кнопка-модификатор: BTN_RIGHT, BTN_MIDDLE.</summary>
    public string TriggerButton { get; set; } = "BTN_RIGHT";

    /// <summary>Короче какого росчерка это не жест, а обычный щелчок.</summary>
    public double MinStrokePx { get; set; } = 40.0;

    public double MinScore { get; set; } = 0.80;
    public double MinMargin { get; set; } = 0.05;

    /// <summary>Что делать с неопознанным росчерком: passthrough | swallow.</summary>
    public string Unrecognized { get; set; } = "passthrough";

    public List<string> ExcludedApps { get; set; } = new();
    public bool PauseInFullscreen { get; set; } = false;
    public bool ShowGestureName { get; set; } = true;
    public int HintDelayMs { get; set; } = 700;
    public double MenuStepPx { get; set; } = 36.0;
    public int MenuTimeoutMs { get; set; } = 5000;

    /// <summary>Спрашивать страницу выпусков, не вышла ли версия новее.</summary>
    public bool CheckUpdates { get; set; } = true;

    /// <summary>Где лежат выпуски, «владелец/хранилище»; пусто — как в коде.</summary>
    public string UpdateRepo { get; set; } = string.Empty;

    public OverlaySettings Overlay { get; set; } = new();
    public string LogLevel { get; set; } = "info";
}
