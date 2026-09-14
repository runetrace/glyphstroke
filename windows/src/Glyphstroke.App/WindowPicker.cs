using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Glyphstroke.App;

/// <summary>
/// Кнопка-мишень: нажать и перетащить на нужное окно — в поле добавится строка
/// «class:программа.exe». Так же, как в версии для Linux, человеку не нужно
/// знать имя процесса заранее.
/// </summary>
/// <remarks>
/// Пока кнопка держит мышь (Mouse.Capture), WPF отдаёт ей события и за пределами
/// окна, поэтому отпускание над чужим окном мы ловим и читаем окно под курсором.
/// На время наведения делаем своё окно полупрозрачным — иначе цель за ним не
/// видно.
/// </remarks>
internal static class WindowPicker
{
    public static Button Target(TextBox field)
    {
        var button = new Button
        {
            Content = L.Tr("Выбрать окно…"),
            Padding = new Thickness(10, 3, 10, 3),
            VerticalAlignment = VerticalAlignment.Top,
            ToolTip = L.Tr("Нажмите и перетащите на нужное окно"),
        };

        Window? owner = null;
        double ownerOpacity = 1.0;

        button.PreviewMouseLeftButtonDown += (_, e) =>
        {
            e.Handled = true;
            button.CaptureMouse();
            button.Cursor = Cursors.Cross;
            owner = Window.GetWindow(button);
            if (owner is not null)
            {
                ownerOpacity = owner.Opacity;
                owner.Opacity = 0.35;
            }
        };

        button.MouseLeftButtonUp += (_, e) =>
        {
            if (!button.IsMouseCaptured)
            {
                return;
            }
            button.ReleaseMouseCapture();
            button.Cursor = null;
            if (owner is not null)
            {
                owner.Opacity = ownerOpacity;
            }

            if (!Native.GetCursorPos(out var point))
            {
                return;
            }
            string? name = WindowContext.ProcessUnder(point);
            if (name is null)
            {
                return;
            }
            string pattern = $"class:{name}";
            var lines = field.Text
                .Split(new[] { '\r', '\n' }, System.StringSplitOptions.RemoveEmptyEntries)
                .Select(line => line.Trim())
                .Where(line => line.Length > 0)
                .ToList();
            if (lines.Contains(pattern))
            {
                return;
            }
            lines.Add(pattern);
            field.Text = string.Join(System.Environment.NewLine, lines);
        };

        return button;
    }
}
