using System;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Glyphstroke.App;

/// <summary>
/// Кнопка-мишень: нажать и перетащить на нужное окно — вызывающему прилетает
/// строка «class:программа.exe». Имя процесса пользователю знать не нужно, он
/// просто наводит мишень на окно программы.
/// </summary>
/// <remarks>
/// Пока кнопка держит мышь (CaptureMouse), Windows шлёт события ей же и за
/// пределами окна, поэтому отпускание над чужим окном мы ловим и читаем процесс
/// под курсором. На время наведения окно делаем полупрозрачным — иначе цель за
/// ним не видно.
///
/// Отпускание слушаем в PreviewMouseLeftButtonUp, а НЕ в обычном
/// MouseLeftButtonUp: ButtonBase помечает обычное событие обработанным у себя
/// внутри (так рождается Click), и наш обработчик до него не доходил — окно
/// оставалось затемнённым, а программа в список не добавлялась. Возврат
/// прозрачности вынесен в LostMouseCapture — единая точка на все случаи, включая
/// перехваченный чужим окном курсор.
/// </remarks>
internal static class WindowPicker
{
    public static Button Target(Action<string> onPicked)
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
            owner = Window.GetWindow(button);
            if (owner is not null)
            {
                ownerOpacity = owner.Opacity;
                owner.Opacity = 0.35;
            }
            button.Cursor = Cursors.Cross;
            button.CaptureMouse();
        };

        // Единая точка восстановления: и штатное отпускание (через
        // ReleaseMouseCapture ниже), и потерю захвата (Alt+Tab, чужой диалог)
        // приводят сюда — окно не останется прозрачным.
        button.LostMouseCapture += (_, _) =>
        {
            button.Cursor = null;
            if (owner is not null)
            {
                owner.Opacity = ownerOpacity;
            }
        };

        button.PreviewMouseLeftButtonUp += (_, e) =>
        {
            if (!button.IsMouseCaptured)
            {
                return;
            }
            e.Handled = true;
            button.ReleaseMouseCapture();

            if (!Native.GetCursorPos(out var point))
            {
                return;
            }
            string? name = WindowContext.ProcessUnder(point);
            if (name is null)
            {
                return;
            }
            // Клик по самой кнопке навёл бы мишень на окно Glyphstroke — не добавляем себя.
            if (string.Equals(name, SelfExe, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
            onPicked($"class:{name}");
        };

        return button;
    }

    private static readonly string SelfExe = Process.GetCurrentProcess().ProcessName + ".exe";
}
