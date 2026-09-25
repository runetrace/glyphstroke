using Glyphstroke.Core;

namespace Glyphstroke.App;

/// <summary>Связка всего: перехват мыши, след, распознавание, выполнение.</summary>
/// <remarks>
/// Здесь принимается главное решение каждого росчерка — забрать щелчок себе или
/// отдать программе. Правило то же, что в версиях для Linux и macOS: щелчок
/// забирается, только если жест действительно выполнен. Коротким движением
/// человек хотел открыть контекстное меню, а неопознанный росчерк — это промах,
/// и молча съедать его нельзя: пользователь решит, что мышь сломалась.
/// </remarks>
public sealed class GestureEngine : IMouseHookListener, IDisposable
{
    private readonly Store _store;
    private readonly MouseHook _hook;
    private readonly TrailWindow _trail;
    private readonly ActionRunner _actions = new();

    private Settings _settings;
    private List<Gesture> _gestures = new();
    private Recognizer _recognizer = new(Array.Empty<GestureDefinition>());

    private readonly List<Point> _stroke = new();
    private string? _strokeApp;
    private IntPtr _targetWindow;   // окно под началом росчерка — цель действий

    public Action<string>? OnLog { get; set; }
    public Action<Match>? OnRecognized { get; set; }

    public GestureEngine(Store store, TrailWindow trail)
    {
        _store = store;
        _trail = trail;
        _settings = store.LoadSettings();
        _hook = new MouseHook(this);
        _actions.OnLog = message => OnLog?.Invoke(message);
        Reload();
    }

    public bool Paused
    {
        get => _hook.Paused;
        set
        {
            _hook.Paused = value;
            if (value)
            {
                _trail.Cancel();
            }
            WindowContext.Forget();
            Log(value ? "перехват на паузе" : "перехват продолжен");
        }
    }

    public bool IsRunning => _hook.IsRunning;

    public int GestureCount => _gestures.Count(gesture => gesture.Enabled);

    public Settings Settings => _settings;

    /// <summary>Перечитать настройки и жесты с диска.</summary>
    public void Reload()
    {
        _settings = _store.LoadSettings();
        _gestures = _store.LoadGestures();
        _trail.Settings = _settings.Overlay;
        _hook.TriggerButton = _settings.TriggerButton;
        Rebuild(null);
        Log($"жестов загружено: {GestureCount}");
    }

    public void Start()
    {
        _hook.Start();
        Log($"перехват включён, кнопка-модификатор: {_settings.TriggerButton}");
    }

    public void Stop()
    {
        _hook.Stop();
        _trail.Cancel();
    }

    public void Dispose() => Stop();

    // --- перехватчик ---

    public bool StrokeBegan(Point point)
    {
        _stroke.Clear();
        _strokeApp = WindowContext.Current();
        // Цель действий — окно под точкой начала росчерка, а не активное окно.
        _targetWindow = WindowContext.WindowUnder((int)point.X, (int)point.Y);

        // Исключённые и полноэкранные — не наш случай: возвращаем false, и
        // перехватчик отдаёт нажатие программе как есть (без глотания и подмены).
        if (IsExcluded(_strokeApp))
        {
            return false;
        }
        if (_settings.PauseInFullscreen && WindowContext.IsFullscreen())
        {
            return false;
        }

        _stroke.Add(point);
        Rebuild(_strokeApp);
        // НЕ блокируем колбэк хука: рисуем след асинхронно.
        _trail.Dispatcher.InvokeAsync(() => _trail.Begin(point));
        return true;
    }

    public void StrokeExtended(Point point)
    {
        if (_stroke.Count == 0)
        {
            return;
        }
        _stroke.Add(point);
        _trail.Dispatcher.InvokeAsync(() => _trail.Extend(point));
    }

    public bool StrokeEnded(Point point)
    {
        if (_stroke.Count == 0)
        {
            return false;
        }
        _stroke.Add(point);
        _trail.Dispatcher.InvokeAsync(() => _trail.End());

        double length = Geometry.PathLength(_stroke);
        var stroke = _stroke.ToList();
        _stroke.Clear();

        if (length < _settings.MinStrokePx)
        {
            // Это не росчерк, а обычный щелчок: пусть уходит программе.
            return false;
        }

        var match = _recognizer.Recognize(stroke);
        OnRecognized?.Invoke(match);

        var gesture = match.Name is null
            ? null
            : _gestures.FirstOrDefault(item => item.Enabled && item.Name == match.Name);

        if (gesture is null)
        {
            string closest = match.RunnerUp is null
                ? string.Empty
                : $", ближе всех «{match.RunnerUp}» ({match.RunnerUpScore * 100:0}%)";
            Log($"не опознано: {match.Code}{closest}");
            // Неопознанный росчерк по умолчанию отдаём программе целиком.
            return string.Equals(_settings.Unrecognized, "swallow", StringComparison.OrdinalIgnoreCase);
        }

        Log($"жест «{gesture.Name}» ({match.Code}, {match.Score * 100:0}%)");
        if (gesture.Menu.Count > 0)
        {
            // Есть пункты — вместо своих действий жест открывает меню у курсора.
            Native.GetCursorPos(out var at);
            var items = gesture.Menu.ToList();
            int timeout = _settings.MenuTimeoutMs;
            var target = _targetWindow;
            _trail.Dispatcher.InvokeAsync(() =>
            {
                var overlay = new MenuOverlay(items, at, timeout, item => _actions.Run(item.Actions, target));
                overlay.Show();
                overlay.Activate();
            });
            return true;
        }
        // Действия — в фоновый поток: они могут запускать программы и слать
        // ввод, и держать на этом колбэк хука нельзя (замёрзнет мышь всей системы).
        var actions = gesture.Actions.ToList();
        var target = _targetWindow;
        Task.Run(() => _actions.Run(actions, target));
        return true;
    }

    // --- внутреннее ---

    /// <summary>Собрать распознаватель из жестов, подходящих текущей программе.</summary>
    /// <remarks>
    /// Отбор до распознавания, а не после, — не ради скорости: жест «вниз» в
    /// браузере и жест «вниз» в терминале могут быть разными, и лишний кандидат
    /// портил бы отрыв от второго места, из-за чего не сработал бы ни один.
    /// </remarks>
    private void Rebuild(string? app)
    {
        var usable = _gestures
            .Where(gesture => gesture.Enabled && gesture.Event.Length == 0 && gesture.Matches(app))
            .Select(gesture => gesture.ToDefinition())
            .ToList();
        _recognizer = new Recognizer(usable, _settings.MinScore, _settings.MinMargin);
    }

    private bool IsExcluded(string? app)
    {
        if (app is null || _settings.ExcludedApps.Count == 0)
        {
            return false;
        }
        return _settings.ExcludedApps.Any(pattern => Gesture.AppMatches(pattern, app));
    }

    private void Log(string message) => OnLog?.Invoke(message);
}
