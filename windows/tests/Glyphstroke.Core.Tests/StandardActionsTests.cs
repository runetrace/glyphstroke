using Glyphstroke.Core;
using Xunit;

namespace Glyphstroke.Core.Tests;

/// <summary>Стандартные действия: состав таблицы и совпадение с другими системами.</summary>
public class StandardActionsTests
{
    /// <summary>
    /// Список имён, записанный в <c>glyphstroke/standard.py</c> (Linux) и
    /// <c>StandardActions.swift</c> (macOS).
    /// </summary>
    /// <remarks>
    /// Пусть лежит здесь копией: разъехавшиеся имена — это молча переставший
    /// работать жест, перенесённый с другой машины, а такую поломку человек не
    /// свяжет с обновлением. Меняется список — правятся все три стороны и эта
    /// строка, и тогда правка видна в истории.
    /// </remarks>
    private static readonly string[] ExpectedIds =
    {
        "copy", "cut", "paste", "delete", "undo", "redo", "select-all",
        "new", "open", "save", "print", "find",
        "new-tab", "close-tab", "next-tab", "prev-tab", "back", "forward", "refresh",
        "zoom-in", "zoom-out", "zoom-reset",
        "minimize", "maximize", "unmaximize", "fullscreen", "close-window", "switch-window",
        "quit", "screenshot",
    };

    [Fact]
    public void IdsMatchTheOtherSystems() =>
        Assert.Equal(ExpectedIds, StandardActions.All.Select(action => action.Id).ToArray());

    [Fact]
    public void EveryIdIsFound()
    {
        foreach (string id in ExpectedIds)
        {
            Assert.NotNull(StandardActions.Find(id));
        }
    }

    [Fact]
    public void NameIsCaseInsensitive()
    {
        Assert.Equal("copy", StandardActions.Find("Copy")?.Id);
        Assert.Equal("paste", StandardActions.Find("  PASTE ")?.Id);
    }

    [Fact]
    public void UnknownNameIsNotFound()
    {
        Assert.Null(StandardActions.Find("потанцевать"));
        Assert.Null(StandardActions.Find(""));
    }

    [Fact]
    public void WindowActionsUseTheWindowKind()
    {
        foreach (string id in new[] { "minimize", "maximize", "unmaximize", "close-window" })
        {
            Assert.Equal(StandardKind.Window, StandardActions.Find(id)!.Kind);
        }
    }

    [Fact]
    public void EditingActionsUseControl()
    {
        // Ctrl, а не Cmd: это и есть причина, по которой таблица здесь своя.
        foreach (string id in new[] { "copy", "cut", "paste", "undo", "select-all", "save" })
        {
            Assert.StartsWith("ctrl+", StandardActions.Find(id)!.Value);
        }
    }

    [Fact]
    public void DescriptionShowsTheCombination()
    {
        Assert.Equal("Вставить — Ctrl+V", StandardActions.Describe("paste"));
        Assert.Equal("Предыдущая вкладка — Ctrl+PageUp", StandardActions.Describe("prev-tab"));
        Assert.Equal("Назад — Alt+←", StandardActions.Describe("back"));
    }

    [Fact]
    public void WindowActionsHaveNoCombinationToShow() =>
        Assert.Equal("Свернуть окно", StandardActions.Describe("minimize"));

    [Fact]
    public void TitleFallsBackToTheName()
    {
        Assert.Equal("Копировать", StandardActions.Title("copy"));
        Assert.Equal("нет-такого", StandardActions.Title("нет-такого"));
    }
}
