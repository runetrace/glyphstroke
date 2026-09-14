namespace Glyphstroke.Core;

/// <summary>Что делать по стандартному действию: клавиши или команда окну.</summary>
public enum StandardKind
{
    Keys,
    Window,
}

public sealed record StandardAction(string Id, string Title, StandardKind Kind, string Value);

/// <summary>
/// Стандартные действия системы: «копировать», «свернуть окно» и прочие.
/// </summary>
/// <remarks>
/// Зачем отдельный тип действия, когда есть «клавиши». Во-первых, человеку не
/// нужно помнить сочетания — он выбирает из списка. Во-вторых и главное, запись
/// остаётся верной при переносе: файл жеста со «стандартным» действием работает
/// на всех трёх системах, потому что клавиши подставляет та, где он выполняется.
///
/// <b>Имена обязаны совпадать</b> с таблицами в <c>glyphstroke/standard.py</c>
/// (Linux) и <c>StandardActions.swift</c> (macOS). Разъедутся — перенесённый
/// жест молча перестанет работать, а это ровно та беда, ради которой тип и
/// заводился. Совпадение стережёт тест.
/// </remarks>
public static class StandardActions
{
    /// <summary>Порядок смысловой, а не алфавитный: правка рядом с правкой.</summary>
    public static readonly IReadOnlyList<StandardAction> All = new List<StandardAction>
    {
        // правка
        new("copy", "Копировать", StandardKind.Keys, "ctrl+c"),
        new("cut", "Вырезать", StandardKind.Keys, "ctrl+x"),
        new("paste", "Вставить", StandardKind.Keys, "ctrl+v"),
        new("delete", "Удалить", StandardKind.Keys, "delete"),
        new("undo", "Отменить", StandardKind.Keys, "ctrl+z"),
        new("redo", "Повторить", StandardKind.Keys, "ctrl+y"),
        new("select-all", "Выделить всё", StandardKind.Keys, "ctrl+a"),
        // файлы
        new("new", "Создать", StandardKind.Keys, "ctrl+n"),
        new("open", "Открыть", StandardKind.Keys, "ctrl+o"),
        new("save", "Сохранить", StandardKind.Keys, "ctrl+s"),
        new("print", "Печать", StandardKind.Keys, "ctrl+p"),
        new("find", "Найти", StandardKind.Keys, "ctrl+f"),
        // вкладки и страницы
        new("new-tab", "Новая вкладка", StandardKind.Keys, "ctrl+t"),
        new("close-tab", "Закрыть вкладку", StandardKind.Keys, "ctrl+w"),
        new("next-tab", "Следующая вкладка", StandardKind.Keys, "ctrl+pagedown"),
        new("prev-tab", "Предыдущая вкладка", StandardKind.Keys, "ctrl+pageup"),
        new("back", "Назад", StandardKind.Keys, "alt+left"),
        new("forward", "Вперёд", StandardKind.Keys, "alt+right"),
        new("refresh", "Обновить", StandardKind.Keys, "f5"),
        // масштаб
        new("zoom-in", "Крупнее", StandardKind.Keys, "ctrl+plus"),
        new("zoom-out", "Мельче", StandardKind.Keys, "ctrl+minus"),
        new("zoom-reset", "Обычный размер", StandardKind.Keys, "ctrl+0"),
        // окна
        new("minimize", "Свернуть окно", StandardKind.Window, "minimize"),
        new("maximize", "Развернуть окно", StandardKind.Window, "maximize"),
        new("unmaximize", "Вернуть размер окна", StandardKind.Window, "unmaximize"),
        new("fullscreen", "Во весь экран", StandardKind.Keys, "f11"),
        new("close-window", "Закрыть окно", StandardKind.Window, "close"),
        new("switch-window", "Переключить окно", StandardKind.Keys, "alt+tab"),
        // прочее
        new("quit", "Завершить программу", StandardKind.Keys, "alt+f4"),
        // Win+Shift+S — снимок области, штатный способ в Windows 10 и новее.
        new("screenshot", "Снимок экрана", StandardKind.Keys, "win+shift+s"),
    };

    private static readonly Dictionary<string, StandardAction> ById =
        All.ToDictionary(action => action.Id, StringComparer.OrdinalIgnoreCase);

    public static StandardAction? Find(string? id) =>
        id is not null && ById.TryGetValue(id.Trim(), out var action) ? action : null;

    /// <summary>Название действия для списков и журнала.</summary>
    public static string Title(string id) => Find(id)?.Title ?? id;

    /// <summary>Название вместе с сочетанием: «Вставить — Ctrl+V».</summary>
    /// <remarks>
    /// Сочетание показывается прямо в списке: выбирая пункт из трёх десятков,
    /// человек обычно хочет знать, что именно нажмётся. У действий над окном
    /// показывать нечего — там не клавиши, а прямая команда окну.
    /// </remarks>
    public static string Describe(string id)
    {
        var action = Find(id);
        if (action is null)
        {
            return id;
        }
        return action.Kind == StandardKind.Keys ? $"{action.Title} — {Pretty(action.Value)}" : action.Title;
    }

    /// <summary><c>ctrl+pagedown</c> → <c>Ctrl+PageDown</c>: так пишут в Windows.</summary>
    public static string Pretty(string combination)
    {
        var names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["ctrl"] = "Ctrl", ["control"] = "Ctrl",
            ["alt"] = "Alt", ["shift"] = "Shift",
            ["win"] = "Win", ["super"] = "Win", ["meta"] = "Win", ["cmd"] = "Win",
            ["pageup"] = "PageUp", ["page_up"] = "PageUp",
            ["pagedown"] = "PageDown", ["page_down"] = "PageDown",
            ["left"] = "←", ["right"] = "→", ["up"] = "↑", ["down"] = "↓",
            ["plus"] = "+", ["minus"] = "−", ["equal"] = "=",
            ["delete"] = "Delete", ["backspace"] = "Backspace", ["tab"] = "Tab",
            ["space"] = "Space", ["enter"] = "Enter", ["return"] = "Enter", ["escape"] = "Esc",
        };
        var parts = combination.Split('+', StringSplitOptions.RemoveEmptyEntries)
            .Select(part => part.Trim())
            .Select(part => names.TryGetValue(part, out var pretty) ? pretty : part.ToUpperInvariant());
        return string.Join("+", parts);
    }
}
