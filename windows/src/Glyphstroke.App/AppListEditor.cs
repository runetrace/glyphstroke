using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;

namespace Glyphstroke.App;

/// <summary>
/// Список программ (для жеста или для исключений): строки добавляет только
/// кнопка-мишень, каждую можно снять крестиком. Ручной ввод под Windows
/// намеренно недоступен — имя процесса (chrome.exe) пользователю негде взять,
/// поэтому программу указывают наведением мишени на её окно. Как в версии для
/// Linux.
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
        picker.HorizontalAlignment = HorizontalAlignment.Left;
        picker.Margin = new Thickness(0, 2, 0, 6);

        Panel.Children.Add(picker);
        Panel.Children.Add(_rows);
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
            }, "RcMuted"));
            return;
        }
        foreach (var pattern in _items.ToList())
        {
            string captured = pattern;
            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
            row.Children.Add(new TextBlock
            {
                Text = captured,
                VerticalAlignment = VerticalAlignment.Center,
                Width = 300,
                TextTrimming = TextTrimming.CharacterEllipsis,
            });
            var remove = new Button
            {
                Content = "×",
                Margin = new Thickness(6, 0, 0, 0),
                Padding = new Thickness(6, 0, 6, 0),
            };
            remove.Click += (_, _) =>
            {
                _items.Remove(captured);
                Render();
                _onChanged();
            };
            row.Children.Add(remove);
            _rows.Children.Add(row);
        }
    }
}
