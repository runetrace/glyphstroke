using System.Windows;
using System.Windows.Interop;
using System.Runtime.InteropServices;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using Glyphstroke.Core;
using Point = Glyphstroke.Core.Point;

namespace Glyphstroke.App;

/// <summary>След за курсором: прозрачное окно поверх всего экрана.</summary>
/// <remarks>
/// Два подводных камня.
///
/// <b>Окно должно быть одно на все мониторы.</b> Иначе росчерк, начатый на
/// одном экране и уведённый на другой, обрывался бы на границе.
///
/// <b>Единицы разные.</b> Перехватчик отдаёт положение курсора в настоящих
/// точках экрана, а WPF рисует в своих, не зависящих от плотности. При
/// масштабе 125 или 150 процентов — а на ноутбуках это норма — след без
/// перевода поехал бы вбок тем сильнее, чем дальше от начала координат.
/// Перевод сделан в одном месте, <see cref="ToWindow"/>.
/// </remarks>
public sealed class TrailWindow : Window
{
    private readonly Polyline _line = new();
    private readonly Canvas _canvas = new();
    private OverlaySettings _settings;

    public TrailWindow(OverlaySettings settings)
    {
        _settings = settings;

        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        Background = Brushes.Transparent;
        Topmost = true;
        ShowInTaskbar = false;
        ResizeMode = ResizeMode.NoResize;
        ShowActivated = false;
        IsHitTestVisible = false;          // след не должен ловить щелчки
        Focusable = false;

        _line.StrokeLineJoin = PenLineJoin.Round;
        _line.StrokeStartLineCap = PenLineCap.Round;
        _line.StrokeEndLineCap = PenLineCap.Round;
        _canvas.Children.Add(_line);
        Content = _canvas;

        ApplyStyle();
        CoverAllScreens();
    }

    public OverlaySettings Settings
    {
        get => _settings;
        set
        {
            _settings = value;
            ApplyStyle();
        }
    }

    public void Begin(Point point)
    {
        if (!_settings.Enabled)
        {
            return;
        }
        CoverAllScreens();
        _line.BeginAnimation(OpacityProperty, null);
        _line.Opacity = _settings.Opacity;
        _line.Points = new PointCollection { ToWindow(point) };
        // Окно показано с самого старта и не прячется между росчерками:
        // переключать видимость топового полноэкранного окна — как раз то,
        // что заставляет мерцать панель задач и рабочий стол.
    }

    public void Extend(Point point)
    {
        if (!_settings.Enabled || _line.Points.Count == 0)
        {
            return;
        }
        var converted = ToWindow(point);
        var last = _line.Points[^1];
        // Точки в один пиксель только утяжеляют путь, рисунок от них не меняется.
        if (Math.Abs(converted.X - last.X) < 1 && Math.Abs(converted.Y - last.Y) < 1)
        {
            return;
        }
        _line.Points.Add(converted);
    }

    /// <summary>Закончить росчерк: погасить след.</summary>
    public void End()
    {
        var fade = new DoubleAnimation(_line.Opacity, 0,
            TimeSpan.FromMilliseconds(Math.Max(0, _settings.FadeMs)));
        fade.Completed += (_, _) => _line.Points.Clear();
        _line.BeginAnimation(OpacityProperty, fade);
    }

    /// <summary>Убрать след немедленно — например, когда перехват встал на паузу.</summary>
    public void Cancel()
    {
        _line.BeginAnimation(OpacityProperty, null);
        _line.Points.Clear();
    }

    /// <summary>
    /// Сделать окно по-настоящему сквозным на уровне ОС и не активирующимся.
    /// </summary>
    /// <remarks>
    /// В WPF <c>IsHitTestVisible=false</c> отключает попадания только внутри
    /// приложения — для других окон окно всё равно ловит щелчки. Настоящую
    /// сквозность даёт стиль WS_EX_TRANSPARENT. Заодно WS_EX_NOACTIVATE и
    /// WS_EX_TOOLWINDOW: окно не забирает фокус и не мелькает в переключателе.
    /// </remarks>
    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);
        var hwnd = new WindowInteropHelper(this).Handle;
        const int GWL_EXSTYLE = -20;
        const int WS_EX_TRANSPARENT = 0x20, WS_EX_LAYERED = 0x80000;
        const int WS_EX_NOACTIVATE = 0x08000000, WS_EX_TOOLWINDOW = 0x80;
        int ex = GetWindowLong(hwnd, GWL_EXSTYLE);
        SetWindowLong(hwnd, GWL_EXSTYLE,
            ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW);
    }

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hwnd, int index);

    [DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hwnd, int index, int value);

    private void ApplyStyle()
    {
        _line.StrokeThickness = Math.Max(1, _settings.Width);
        _line.Stroke = new SolidColorBrush(ParseColor(_settings.Color));
        _line.Opacity = _settings.Opacity;
    }

    private void CoverAllScreens()
    {
        Left = SystemParameters.VirtualScreenLeft;
        Top = SystemParameters.VirtualScreenTop;
        Width = SystemParameters.VirtualScreenWidth;
        Height = SystemParameters.VirtualScreenHeight;
    }

    /// <summary>Точка экрана → точка внутри окна, с поправкой на масштаб.</summary>
    private System.Windows.Point ToWindow(Point point)
    {
        var source = PresentationSource.FromVisual(this);
        var device = new System.Windows.Point(point.X, point.Y);
        var scaled = source?.CompositionTarget is not null
            ? source.CompositionTarget.TransformFromDevice.Transform(device)
            : device;
        return new System.Windows.Point(scaled.X - Left, scaled.Y - Top);
    }

    /// <summary><c>#4da3ff</c> → цвет. Негодная запись не должна оставлять след
    /// невидимым, поэтому при разборе возвращаем заметный синий.</summary>
    public static Color ParseColor(string text)
    {
        string hex = (text ?? string.Empty).Trim().TrimStart('#');
        if (hex.Length == 6 && uint.TryParse(hex, System.Globalization.NumberStyles.HexNumber,
                                             System.Globalization.CultureInfo.InvariantCulture, out uint value))
        {
            return Color.FromRgb((byte)(value >> 16), (byte)(value >> 8), (byte)value);
        }
        return Color.FromRgb(0x4D, 0xA3, 0xFF);
    }
}
