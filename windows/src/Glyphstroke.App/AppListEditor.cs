using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;

namespace Glyphstroke.App;

/// <summary>
/// Список программ (для жеста или для исключений) единым полем на всю ширину:
/// строки-программы с крестиком внутри рамки, снизу кнопка-мишень «Выбрать
/// окно». Ручной ввод под Windows намеренно недоступен — имя процесса
/// (chrome.exe) пользователю негде взять, поэтому программу указывают наведением
/// мишени на её окно. Как в версии для Linux.
/// </summary>
internal sealed class AppListEditor
{
    public StackPanel Panel { get; } = new();

    private readonly StackPanel _rows = new();
    private readonly Action _onChanged;
    private readonly string _emptyText;
    private List<string> _items = new();

    public AppListEditor(Action onChanged, string emptyText)
    {
        _onChanged = onChanged;
        _emptyText = emptyText;

        // Поле-рамка на всю ширину: внутри — строки программ или подсказка.
        var box = new Border
        {
            CornerRadius = new CornerRadius(8),
            BorderThickness = new Thickness(1),
            Padding = new Thickness(10),
            MinHeight = 44,
            Child = _rows,
        };
        box.SetResourceReference(Border.BackgroundProperty, "RcField");
        box.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");

        // Кнопка-мишень: навести на окно нужной программы.
        var picker = WindowPicker.Target(pattern =>
        {
            if (_items.Contains(pattern))
            {
                return;
            }
            _items.Add(pattern);
            Render();
            _onChanged();
        });
        picker.Content = "🎯 " + L.Tr("Выбрать окно…");
        picker.HorizontalAlignment = HorizontalAlignment.Left;
        picker.Margin = new Thickness(0, 8, 0, 0);

        Panel.Children.Add(box);
        Panel.Children.Add(picker);
    }

    /// <summary>Показывать и править именно этот список — по ссылке, так что
    /// добавление и удаление сразу видны вызывающему.</summary>
    public void Load(List<string> items)
    {
        _items = items;
        Render();
    }

    private void Render()
    {
        _rows.Children.Clear();
        if (_items.Count == 0)
        {
            _rows.Children.Add(Theme.Themed(new TextBlock
            {
                Text = _emptyText,
                FontSize = 12,
                VerticalAlignment = VerticalAlignment.Center,
            }, "RcMuted"));
            return;
        }
        foreach (var pattern in _items.ToList())
        {
            string captured = pattern;
            var row = new DockPanel { Margin = new Thickness(0, 2, 0, 2), LastChildFill = true };

            var remove = new Button
            {
                Content = "✕",
                Margin = new Thickness(8, 0, 0, 0),
                Padding = new Thickness(6, 0, 6, 0),
                VerticalAlignment = VerticalAlignment.Center,
                ToolTip = L.Tr("Убрать программу"),
            };
            remove.Click += (_, _) =>
            {
                _items.Remove(captured);
                Render();
                _onChanged();
            };
            DockPanel.SetDock(remove, Dock.Right);
            row.Children.Add(remove);

            row.Children.Add(new TextBlock
            {
                Text = captured,
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
            });
            _rows.Children.Add(row);
        }
    }
}
