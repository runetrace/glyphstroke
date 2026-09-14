using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using Glyphstroke.Core;
using MenuItem = Glyphstroke.Core.MenuItem;

namespace Glyphstroke.App;

/// <summary>
/// Меню под жестом: список пунктов у курсора, выбор — щелчком.
/// </summary>
/// <remarks>
/// На Linux меню выбирается движением при зажатой кнопке — там демон держит
/// мышь. На Windows жест завершается на отпускании кнопки, держать нечего,
/// поэтому пункт выбирается обычным щелчком: то же меню под жестом, только
/// подтверждение привычнее для системы. Закрывается щелчком мимо, Esc или сам
/// по времени — потерять его нельзя.
/// </remarks>
internal sealed class MenuOverlay : Window
{
    private readonly Action<MenuItem> _chosen;
    private readonly Native.POINT _at;
    private readonly DispatcherTimer _timeout = new();

    public MenuOverlay(IReadOnlyList<MenuItem> items, Native.POINT at, int timeoutMs, Action<MenuItem> chosen)
    {
        _chosen = chosen;
        _at = at;

        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        Topmost = true;
        SizeToContent = SizeToContent.WidthAndHeight;
        WindowStartupLocation = WindowStartupLocation.Manual;
        AllowsTransparency = true;
        Background = Brushes.Transparent;

        var panel = new StackPanel();
        foreach (var item in items)
        {
            var captured = item;
            var button = new Button
            {
                Content = string.IsNullOrWhiteSpace(item.Name) ? L.Tr("Пункт") : item.Name,
                Padding = new Thickness(14, 6, 14, 6),
                HorizontalContentAlignment = HorizontalAlignment.Left,
                Margin = new Thickness(0, 1, 0, 1),
            };
            button.Click += (_, _) => Pick(captured);
            panel.Children.Add(button);
        }

        var card = new Border
        {
            CornerRadius = new CornerRadius(8),
            BorderThickness = new Thickness(1),
            Padding = new Thickness(4),
            Child = panel,
        };
        card.SetResourceReference(Border.BackgroundProperty, "RcCard");
        card.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");
        Content = card;

        Deactivated += (_, _) => Dismiss();
        KeyDown += (_, e) => { if (e.Key == Key.Escape) { Dismiss(); } };
        _timeout.Interval = TimeSpan.FromMilliseconds(Math.Max(1000, timeoutMs));
        _timeout.Tick += (_, _) => Dismiss();
        _timeout.Start();

        SourceInitialized += (_, _) =>
        {
            Theme.ApplyWindowChrome(this);
            // Позиция курсора в аппаратных точках → в точки WPF по масштабу экрана.
            var dpi = VisualTreeHelper.GetDpi(this);
            Left = _at.X / dpi.DpiScaleX;
            Top = _at.Y / dpi.DpiScaleY;
        };
    }

    private void Pick(MenuItem item)
    {
        _timeout.Stop();
        Close();
        _chosen(item);
    }

    private void Dismiss()
    {
        _timeout.Stop();
        Close();
    }
}
