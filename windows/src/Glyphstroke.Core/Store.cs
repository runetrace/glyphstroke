using System.Globalization;
using System.Text;
using YamlDotNet.RepresentationModel;

namespace Glyphstroke.Core;

/// <summary>Чтение и запись файлов программы.</summary>
/// <remarks>
/// Формат намеренно тот же, что у версий для Linux и macOS: <c>settings.yaml</c>
/// рядом с каталогом <c>gestures\</c>, в каждом файле один жест. Это не прихоть:
/// жесты человек настраивает долго, и переносить их между машинами он должен
/// копированием каталога, а не экспортом через три диалога.
///
/// Место своё: <c>%APPDATA%\Glyphstroke</c>. Класть настройки рядом с программой
/// в Program Files нельзя — туда нет права записи у обычного пользователя.
/// </remarks>
public sealed class Store
{
    public string Root { get; }

    /// <summary>
    /// Ключи settings.yaml, которых на этой системе нет (устройства ввода,
    /// клавиша тачпада и прочее из Linux). Читаются и сохраняются как есть,
    /// чтобы один файл можно было носить между системами, ничего не теряя.
    /// </summary>
    private readonly Dictionary<string, YamlNode> _extras = new();

    public Store(string? root = null)
    {
        Root = root ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Glyphstroke");
    }

    public string SettingsPath => Path.Combine(Root, "settings.yaml");

    /// <summary>
    /// Текущий набор жестов: пусто — основной (папка <c>gestures\</c>), иначе
    /// имя набора из <c>profiles\</c>. Формат общий с версией для Linux.
    /// </summary>
    public string ActiveProfile { get; set; } = string.Empty;

    public string ProfilesDirectory => Path.Combine(Root, "profiles");

    public string GesturesDirectory => string.IsNullOrWhiteSpace(ActiveProfile)
        ? Path.Combine(Root, "gestures")
        : Path.Combine(ProfilesDirectory, CleanProfileName(ActiveProfile));

    public void PrepareDirectories() => Directory.CreateDirectory(GesturesDirectory);

    // --- наборы жестов (профили) ---

    /// <summary>Имя набора без символов, недопустимых в имени папки.</summary>
    public static string CleanProfileName(string? name) =>
        new string((name ?? string.Empty)
            .Where(ch => !Path.GetInvalidFileNameChars().Contains(ch)).ToArray()).Trim();

    /// <summary>Имена заведённых наборов (без основного), по алфавиту.</summary>
    public IReadOnlyList<string> AvailableProfiles()
    {
        if (!Directory.Exists(ProfilesDirectory))
        {
            return Array.Empty<string>();
        }
        return Directory.EnumerateDirectories(ProfilesDirectory)
            .Select(path => Path.GetFileName(path)!)
            .Where(name => name.Length > 0)
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    /// <summary>Завести набор; <paramref name="copyFrom"/> — откуда скопировать жесты.</summary>
    public string CreateProfile(string name, string? copyFrom = null)
    {
        name = CleanProfileName(name);
        if (name.Length == 0)
        {
            return string.Empty;
        }
        string target = Path.Combine(ProfilesDirectory, name);
        Directory.CreateDirectory(target);
        if (copyFrom is not null)
        {
            string source = string.IsNullOrWhiteSpace(copyFrom)
                ? Path.Combine(Root, "gestures")
                : Path.Combine(ProfilesDirectory, CleanProfileName(copyFrom));
            if (Directory.Exists(source))
            {
                foreach (var file in Directory.EnumerateFiles(source, "*.yaml"))
                {
                    File.Copy(file, Path.Combine(target, Path.GetFileName(file)), overwrite: true);
                }
            }
        }
        return name;
    }

    public void RemoveProfile(string name)
    {
        name = CleanProfileName(name);
        string target = Path.Combine(ProfilesDirectory, name);
        if (name.Length > 0 && Directory.Exists(target))
        {
            Directory.Delete(target, recursive: true);
        }
    }

    // --- настройки ---

    public Settings LoadSettings()
    {
        var settings = new Settings();
        var root = ReadYaml(SettingsPath);
        if (root is null)
        {
            return settings;
        }

        settings.Language = Str(root, "language") ?? settings.Language;
        settings.Theme = Str(root, "theme") ?? settings.Theme;
        settings.ActiveProfile = Str(root, "active_profile") ?? settings.ActiveProfile;
        settings.TriggerButton = Str(root, "trigger_button") ?? settings.TriggerButton;
        settings.MinStrokePx = Num(root, "min_stroke_px") ?? settings.MinStrokePx;
        settings.MinScore = Num(root, "min_score") ?? settings.MinScore;
        settings.MinMargin = Num(root, "min_margin") ?? settings.MinMargin;
        settings.Unrecognized = Str(root, "unrecognized") ?? settings.Unrecognized;
        settings.ExcludedApps = StrList(root, "excluded_apps");
        settings.PauseInFullscreen = Bool(root, "pause_in_fullscreen") ?? settings.PauseInFullscreen;
        settings.ShowGestureName = Bool(root, "show_gesture_name") ?? settings.ShowGestureName;
        settings.HintDelayMs = (int?)Num(root, "hint_delay_ms") ?? settings.HintDelayMs;
        settings.MenuStepPx = Num(root, "menu_step_px") ?? settings.MenuStepPx;
        settings.MenuTimeoutMs = (int?)Num(root, "menu_timeout_ms") ?? settings.MenuTimeoutMs;
        settings.CheckUpdates = Bool(root, "check_updates") ?? settings.CheckUpdates;
        settings.UpdateRepo = Str(root, "update_repo") ?? settings.UpdateRepo;
        settings.LogLevel = Str(root, "log_level") ?? settings.LogLevel;

        if (root.Children.TryGetValue(new YamlScalarNode("overlay"), out var overlayNode)
            && overlayNode is YamlMappingNode overlay)
        {
            settings.Overlay.Enabled = Bool(overlay, "enabled") ?? settings.Overlay.Enabled;
            settings.Overlay.Color = Str(overlay, "color") ?? settings.Overlay.Color;
            settings.Overlay.Width = (int?)Num(overlay, "width") ?? settings.Overlay.Width;
            settings.Overlay.Opacity = Num(overlay, "opacity") ?? settings.Overlay.Opacity;
            settings.Overlay.FadeMs = (int?)Num(overlay, "fade_ms") ?? settings.Overlay.FadeMs;
        }

        _extras.Clear();
        foreach (var pair in root.Children)
        {
            if (pair.Key is YamlScalarNode key && key.Value is not null && !KnownKeys.Contains(key.Value))
            {
                _extras[key.Value] = pair.Value;
            }
        }
        return settings;
    }

    public void SaveSettings(Settings settings)
    {
        PrepareDirectories();
        var text = new StringBuilder();
        text.AppendLine($"language: {Quote(settings.Language)}");
        text.AppendLine($"theme: {Quote(settings.Theme)}");
        text.AppendLine($"active_profile: {Quote(settings.ActiveProfile)}");
        text.AppendLine($"trigger_button: {Quote(settings.TriggerButton)}");
        text.AppendLine($"min_stroke_px: {Number(settings.MinStrokePx)}");
        text.AppendLine($"min_score: {Number(settings.MinScore)}");
        text.AppendLine($"min_margin: {Number(settings.MinMargin)}");
        text.AppendLine($"unrecognized: {Quote(settings.Unrecognized)}");
        text.AppendLine("excluded_apps:" + (settings.ExcludedApps.Count == 0 ? " []" : string.Empty));
        foreach (var pattern in settings.ExcludedApps)
        {
            text.AppendLine($"  - {Quote(pattern)}");
        }
        text.AppendLine($"pause_in_fullscreen: {Flag(settings.PauseInFullscreen)}");
        text.AppendLine($"show_gesture_name: {Flag(settings.ShowGestureName)}");
        text.AppendLine($"hint_delay_ms: {settings.HintDelayMs}");
        text.AppendLine($"menu_step_px: {Number(settings.MenuStepPx)}");
        text.AppendLine($"menu_timeout_ms: {settings.MenuTimeoutMs}");
        text.AppendLine($"check_updates: {Flag(settings.CheckUpdates)}");
        text.AppendLine($"update_repo: {Quote(settings.UpdateRepo)}");
        text.AppendLine($"log_level: {Quote(settings.LogLevel)}");
        text.AppendLine("overlay:");
        text.AppendLine($"  enabled: {Flag(settings.Overlay.Enabled)}");
        text.AppendLine($"  color: {Quote(settings.Overlay.Color)}");
        text.AppendLine($"  width: {settings.Overlay.Width}");
        text.AppendLine($"  opacity: {Number(settings.Overlay.Opacity)}");
        text.AppendLine($"  fade_ms: {settings.Overlay.FadeMs}");

        // Чужие ключи дописываем как есть — их значения мы не разбирали и
        // портить их своим пониманием не имеем права.
        foreach (var extra in _extras)
        {
            text.Append(extra.Key).AppendLine(":" + FormatNode(extra.Value, 1));
        }

        WriteAtomic(SettingsPath, text.ToString());
    }

    private static readonly HashSet<string> KnownKeys = new()
    {
        "language", "theme", "active_profile", "trigger_button", "min_stroke_px", "min_score",
        "min_margin", "unrecognized", "excluded_apps", "pause_in_fullscreen",
        "show_gesture_name", "hint_delay_ms", "menu_step_px", "menu_timeout_ms",
        "check_updates", "update_repo", "log_level", "overlay",
    };

    // --- жесты ---

    public List<Gesture> LoadGestures()
    {
        if (!Directory.Exists(GesturesDirectory))
        {
            return new List<Gesture>();
        }
        return Directory.EnumerateFiles(GesturesDirectory)
            .Where(path => path.EndsWith(".yaml", StringComparison.OrdinalIgnoreCase)
                        || path.EndsWith(".yml", StringComparison.OrdinalIgnoreCase))
            .OrderBy(path => Path.GetFileName(path), StringComparer.OrdinalIgnoreCase)
            .Select(ReadGesture)
            .Where(gesture => gesture is not null)
            .Select(gesture => gesture!)
            .ToList();
    }

    /// <summary>
    /// Прочитать жест из файла. Битый файл не должен ронять весь набор: одна
    /// испорченная запись — это одна пропавшая фигура, а не мёртвая программа.
    /// </summary>
    public static Gesture? ReadGesture(string path)
    {
        var root = ReadYaml(path);
        if (root is null)
        {
            return null;
        }

        var gesture = new Gesture
        {
            Name = Str(root, "name") ?? Path.GetFileNameWithoutExtension(path),
            Enabled = Bool(root, "enabled") ?? true,
            Event = (Str(root, "event") ?? string.Empty).Trim().ToLowerInvariant(),
            Directions = StrList(root, "directions")
                .Select(value => value.Trim().ToUpperInvariant())
                .Where(value => value.Length > 0).ToList(),
            Apps = StrList(root, "apps"),
            RotationTolerance = Num(root, "rotation_tolerance") ?? 20.0,
            Description = Str(root, "description") ?? string.Empty,
            FilePath = path,
        };

        if (root.Children.TryGetValue(new YamlScalarNode("templates"), out var templatesNode)
            && templatesNode is YamlSequenceNode templates)
        {
            foreach (var item in templates)
            {
                gesture.Templates.Add(ParseStroke(item));
            }
        }
        gesture.Actions = ParseActions(root, "actions");

        if (root.Children.TryGetValue(new YamlScalarNode("menu"), out var menuNode)
            && menuNode is YamlSequenceNode menu)
        {
            foreach (var item in menu)
            {
                if (item is not YamlMappingNode entry)
                {
                    continue;
                }
                string name = (Str(entry, "name") ?? string.Empty).Trim();
                if (name.Length == 0)
                {
                    continue;
                }
                gesture.Menu.Add(new MenuItem { Name = name, Actions = ParseActions(entry, "actions") });
            }
        }
        return gesture;
    }

    public string Save(Gesture gesture)
    {
        PrepareDirectories();
        string path = gesture.FilePath
            ?? Path.Combine(GesturesDirectory, Slug(gesture.Name) + ".yaml");

        var text = new StringBuilder();
        text.AppendLine($"name: {Quote(gesture.Name)}");
        text.AppendLine($"enabled: {Flag(gesture.Enabled)}");
        text.AppendLine($"description: {Quote(gesture.Description)}");
        text.AppendLine($"event: {Quote(gesture.Event)}");
        text.AppendLine("directions: [" + string.Join(", ", gesture.Directions) + "]");
        text.AppendLine("apps:" + (gesture.Apps.Count == 0 ? " []" : string.Empty));
        foreach (var pattern in gesture.Apps)
        {
            text.AppendLine($"  - {Quote(pattern)}");
        }
        text.AppendLine($"rotation_tolerance: {Number(gesture.RotationTolerance)}");
        text.AppendLine("actions:" + (gesture.Actions.Count == 0 ? " []" : string.Empty));
        foreach (var action in gesture.Actions)
        {
            text.AppendLine($"  - {{type: {Quote(action.Type)}, value: {Quote(action.Value)}}}");
        }
        // Ключа menu у жеста без меню быть не должно: файл прежнего жеста не
        // должен меняться от одного лишь пересохранения.
        if (gesture.Menu.Count > 0)
        {
            text.AppendLine("menu:");
            foreach (var item in gesture.Menu)
            {
                text.AppendLine($"  - name: {Quote(item.Name)}");
                text.AppendLine("    actions:" + (item.Actions.Count == 0 ? " []" : string.Empty));
                foreach (var action in item.Actions)
                {
                    text.AppendLine($"      - {{type: {Quote(action.Type)}, value: {Quote(action.Value)}}}");
                }
            }
        }
        text.AppendLine("templates:" + (gesture.Templates.Count == 0 ? " []" : string.Empty));
        foreach (var template in gesture.Templates)
        {
            text.AppendLine($"  - {Quote(FormatStroke(template))}");
        }

        WriteAtomic(path, text.ToString());
        gesture.FilePath = path;
        return path;
    }

    public void Delete(Gesture gesture)
    {
        if (gesture.FilePath is not null && File.Exists(gesture.FilePath))
        {
            File.Delete(gesture.FilePath);
        }
    }

    /// <summary>Положить стартовый набор жестов, если каталог пуст.</summary>
    /// <remarks>
    /// Пустой список на первом запуске выглядит поломкой: человек нарисовал
    /// росчерк, ничего не произошло, и понять, программа сломана или просто
    /// нечему срабатывать, нельзя.
    /// </remarks>
    public int InstallStarterGestures(string directory)
    {
        PrepareDirectories();
        if (LoadGestures().Count > 0 || !Directory.Exists(directory))
        {
            return 0;
        }
        int copied = 0;
        foreach (var source in Directory.EnumerateFiles(directory, "*.yaml"))
        {
            string target = Path.Combine(GesturesDirectory, Path.GetFileName(source));
            if (!File.Exists(target))
            {
                File.Copy(source, target);
                copied++;
            }
        }
        return copied;
    }

    // --- мелочи ---

    public static List<Point> ParseStroke(YamlNode node)
    {
        var points = new List<Point>();
        if (node is YamlScalarNode scalar && scalar.Value is not null)
        {
            foreach (var chunk in scalar.Value.Split(new[] { ' ', '\n', '\r', '\t' },
                                                     StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = chunk.Split(',');
                if (parts.Length == 2
                    && double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out double x)
                    && double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double y))
                {
                    points.Add(new Point(x, y));
                }
            }
        }
        else if (node is YamlSequenceNode sequence)
        {
            foreach (var item in sequence)
            {
                if (item is YamlSequenceNode pair && pair.Children.Count >= 2
                    && pair.Children[0] is YamlScalarNode xs && pair.Children[1] is YamlScalarNode ys
                    && double.TryParse(xs.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out double x)
                    && double.TryParse(ys.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out double y))
                {
                    points.Add(new Point(x, y));
                }
            }
        }
        return points;
    }

    public static string FormatStroke(IReadOnlyList<Point> points) =>
        string.Join(" ", points.Select(p =>
            p.X.ToString("0.0", CultureInfo.InvariantCulture) + "," +
            p.Y.ToString("0.0", CultureInfo.InvariantCulture)));

    /// <summary>Имя файла из названия жеста: буквы и цифры, остальное — дефис.</summary>
    public static string Slug(string name)
    {
        var builder = new StringBuilder();
        foreach (char symbol in name.Trim())
        {
            builder.Append(char.IsLetterOrDigit(symbol) || symbol is '.' or '-' or '_' ? symbol : '-');
        }
        string slug = string.Join("-", builder.ToString()
            .Split('-', StringSplitOptions.RemoveEmptyEntries)).ToLowerInvariant();
        return slug.Length == 0 ? "gesture" : slug;
    }

    private static List<GestureAction> ParseActions(YamlMappingNode parent, string key)
    {
        var result = new List<GestureAction>();
        if (!parent.Children.TryGetValue(new YamlScalarNode(key), out var node)
            || node is not YamlSequenceNode sequence)
        {
            return result;
        }
        foreach (var item in sequence)
        {
            if (item is YamlMappingNode entry)
            {
                result.Add(new GestureAction(Str(entry, "type") ?? "none", Str(entry, "value") ?? string.Empty));
            }
        }
        return result;
    }

    private static YamlMappingNode? ReadYaml(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return null;
            }
            var stream = new YamlStream();
            using var reader = new StreamReader(path, Encoding.UTF8);
            stream.Load(reader);
            return stream.Documents.Count > 0 ? stream.Documents[0].RootNode as YamlMappingNode : null;
        }
        catch (Exception)
        {
            // Битый файл — не повод падать: см. примечание к ReadGesture.
            return null;
        }
    }

    /// <summary>Запись через временный файл: обрыв не должен оставлять половину.</summary>
    private static void WriteAtomic(string path, string text)
    {
        string temporary = path + ".tmp";
        File.WriteAllText(temporary, text, new UTF8Encoding(false));
        File.Move(temporary, path, overwrite: true);
    }

    private static string FormatNode(YamlNode node, int indent)
    {
        var document = new YamlStream(new YamlDocument(node));
        using var writer = new StringWriter();
        document.Save(writer, assignAnchors: false);
        string body = writer.ToString().Replace("...", string.Empty).TrimEnd();
        if (node is YamlScalarNode)
        {
            return " " + body.Trim();
        }
        string pad = new(' ', indent * 2);
        var lines = body.Split('\n').Where(line => line.Trim().Length > 0)
            .Select(line => pad + line.TrimEnd());
        return "\n" + string.Join("\n", lines);
    }

    private static string? Str(YamlMappingNode parent, string key) =>
        parent.Children.TryGetValue(new YamlScalarNode(key), out var node)
            && node is YamlScalarNode scalar ? scalar.Value : null;

    private static double? Num(YamlMappingNode parent, string key)
    {
        string? value = Str(parent, key);
        return value is not null
            && double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double result)
            ? result : null;
    }

    private static bool? Bool(YamlMappingNode parent, string key)
    {
        string? value = Str(parent, key)?.Trim().ToLowerInvariant();
        return value switch
        {
            "true" or "yes" or "y" or "on" or "1" => true,
            "false" or "no" or "n" or "off" or "0" => false,
            _ => null,
        };
    }

    private static List<string> StrList(YamlMappingNode parent, string key)
    {
        var result = new List<string>();
        if (parent.Children.TryGetValue(new YamlScalarNode(key), out var node)
            && node is YamlSequenceNode sequence)
        {
            foreach (var item in sequence)
            {
                if (item is YamlScalarNode scalar && scalar.Value is not null)
                {
                    result.Add(scalar.Value);
                }
            }
        }
        return result;
    }

    private static string Quote(string value) =>
        "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n") + "\"";

    private static string Number(double value) => value.ToString("0.###", CultureInfo.InvariantCulture);

    private static string Flag(bool value) => value ? "true" : "false";
}
