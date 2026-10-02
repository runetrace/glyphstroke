using System.Windows;
using System.Windows.Interop;
using System.Runtime.InteropServices;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using System.Windows.Threading;
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
///
/// <b>Точки приходят пачками.</b> Перехватчик зовёт <see cref="PostExtend"/> на
/// каждое движение мыши — у игровых мышей это тысяча раз в секунду. Раньше
/// каждое движение было отдельной операцией в очереди интерфейса: на длинной
/// спирали очередь росла быстрее, чем окно успевало рисовать, след догонял
/// курсор рывками, процессор уходил в перерисовку, а поток перехвата переставал
/// укладываться в срок, и Windows молча снимала хук. Теперь точки копятся в
/// буфере, в очереди всегда не больше одной операции, и за раз рисуется всё
/// накопленное. Длина следа ограничена <see cref="MaxPoints"/>.
/// </remarks>
public sealed class TrailWindow : Window
{
    private readonly Polyline _line = new();
    private readonly Canvas _canvas = new();
    private OverlaySettings _settings;

    /// <summary>Потолок точек следа: дальше путь прореживается вдвое.</summary>
    private const int MaxPoints = 1500;

    /// <summary>Ближе этого (в точках окна) новая точка рисунок не меняет.</summary>
    private const double MinStep = 2.0;

    // Перевод экранных точек в точки окна, снятый в начале росчерка: искать
    // PresentationSource на каждой точке незачем.
    private Matrix _fromDevice = Matrix.Identity;
    private double _originX, _originY;

    // Буфер между потоком перехвата и потоком интерфейса.
    private readonly object _pendingLock = new();
    private readonly List<Point> _pending = new();
    private bool _pendingBegin;
    private Point _pendingBeginPoint;
    private bool _pendingEnd;
    private bool _flushScheduled;

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

    // --- вызовы с потока перехвата ---

    /// <summary>Начать след. Можно звать с любого потока.</summary>
    public void PostBegin(Point point)
    {
        lock (_pendingLock)
        {
            _pending.Clear();
            _pendingBegin = true;
            _pendingBeginPoint = point;
            _pendingEnd = false;
            ScheduleFlush();
        }
    }

    /// <summary>Продолжить след. Можно звать с любого потока.</summary>
    public void PostExtend(Point point)
    {
        lock (_pendingLock)
        {
            // Если интерфейс совсем встал, буфер не должен расти без конца:
            // для рисунка хватит и прореженного пути.
            if (_pending.Count >= MaxPoints * 4)
            {
                Thin(_pending);
            }
            _pending.Add(point);
            ScheduleFlush();
        }
    }

    /// <summary>Закончить след. Можно звать с любого потока.</summary>
    public void PostEnd()
    {
        lock (_pendingLock)
        {
            _pendingEnd = true;
            ScheduleFlush();
        }
    }

    /// <summary>Поставить в очередь одну операцию на всю пачку (под замком).</summary>
    /// <remarks>
    /// Приоритет ниже отрисовки: пока окно рисует, точки копятся, и следующий
    /// проход забирает их разом.
    /// </remarks>
    private void ScheduleFlush()
    {
        if (_flushScheduled)
        {
            return;
        }
        _flushScheduled = true;
        Dispatcher.BeginInvoke(DispatcherPriority.Input, new Action(Flush));
    }

    private void Flush()
    {
        bool begin, end;
        Point beginPoint;
        Point[] points;
        lock (_pendingLock)
        {
            _flushScheduled = false;
            begin = _pendingBegin;
            beginPoint = _pendingBeginPoint;
            end = _pendingEnd;
            points = _pending.ToArray();
            _pending.Clear();
            _pendingBegin = false;
            _pendingEnd = false;
        }
        if (begin)
        {
            Begin(beginPoint);
        }
        foreach (var point in points)
        {
            Extend(point);
        }
        if (end)
        {
            End();
        }
    }

    /// <summary>Выкинуть каждую вторую точку, сохранив последнюю.</summary>
    private static void Thin(List<Point> points)
    {
        if (points.Count < 3)
        {
            return;
        }
        var last = points[^1];
        int write = 0;
        for (int read = 0; read < points.Count; read += 2)
        {
            points[write++] = points[read];
        }
        points.RemoveRange(write, points.Count - write);
        if (points[^1] != last)
        {
            points.Add(last);
        }
    }

    // --- работа на потоке интерфейса ---

    public void Begin(Point point)
    {
        if (!_settings.Enabled)
        {
            return;
        }
        CoverAllScreens();
        var source = PresentationSource.FromVisual(this);
        _fromDevice = source?.CompositionTarget?.TransformFromDevice ?? Matrix.Identity;
        _originX = Left;
        _originY = Top;
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
        // Точки в пару пикселей только утяжеляют путь, рисунок от них не меняется.
        if (Math.Abs(converted.X - last.X) < MinStep && Math.Abs(converted.Y - last.Y) < MinStep)
        {
            return;
        }
        if (_line.Points.Count >= MaxPoints)
        {
            // Длинная спираль: прореживаем уже нарисованное, а не копим тысячи
            // точек, каждую из которых окно перерисовывает целиком.
            var thinned = new PointCollection(MaxPoints / 2 + 2);
            for (int i = 0; i < _line.Points.Count; i += 2)
            {
                thinned.Add(_line.Points[i]);
            }
            _line.Points = thinned;
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
    /// <remarks>Преобразование снимается в <see cref="Begin"/>.</remarks>
    private System.Windows.Point ToWindow(Point point)
    {
        var scaled = _fromDevice.Transform(new System.Windows.Point(point.X, point.Y));
        return new System.Windows.Point(scaled.X - _originX, scaled.Y - _originY);
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
