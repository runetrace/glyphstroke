using System.Runtime.InteropServices;
using System.Threading;
using Glyphstroke.Core;

namespace Glyphstroke.App;

/// <summary>Кому перехватчик рассказывает о росчерке.</summary>
public interface IMouseHookListener
{
    /// <summary>
    /// Кнопку нажали. Вернуть <c>true</c>, если росчерк берём себе (тогда нажатие
    /// глотается, решение — на отпускании), и <c>false</c>, если этот случай не
    /// наш (исключённая программа, полноэкранное) — тогда нажатие идёт программе.
    /// </summary>
    bool StrokeBegan(Point point);
    void StrokeExtended(Point point);

    /// <summary>
    /// Кнопку отпустили. Вернуть <c>true</c>, если щелчок забираем себе (жест
    /// выполнен), и <c>false</c>, если его надо отдать программе.
    /// </summary>
    bool StrokeEnded(Point point);
}

/// <summary>
/// Перехват мыши низкоуровневым хуком — здешний аналог evdev на Linux и
/// CGEventTap на маке.
/// </summary>
/// <remarks>
/// Три вещи, о которые тут легко споткнуться.
///
/// <b>Нажатие забирается сразу.</b> Пока кнопка держится, неизвестно, жест это
/// или обычный щелчок, а отдать нажатие программе задним числом нельзя. Поэтому
/// нажатие глотается всегда, и если росчерка не вышло, мы сами отправляем
/// системе щелчок в той точке, где кнопку нажали.
///
/// <b>Обработчик должен возвращаться быстро.</b> Windows отводит хуку около
/// трети секунды и, не дождавшись, молча выкидывает его из цепочки — мышь при
/// этом «оживает», а программа выглядит сломанной. Поэтому здесь только разбор
/// и решение, а действия жеста уходят в отдельный поток.
///
/// <b>Делегат нужно держать за руку.</b> Если ссылку на него не сохранить,
/// сборщик мусора уберёт его, а система продолжит звать по адресу — это падение
/// без внятного следа, причём случайное по времени.
///
/// <b>Система может снять хук молча.</b> Если обработчик хоть раз не уложился
/// в срок (процессор занят, пауза сборки мусора), Windows 7 и новее просто
/// выкидывает хук — без ошибки и без уведомления. Мышь работает, а жесты нет.
/// Поэтому <see cref="LooksDead"/> сверяет движение курсора с тем, доходят ли
/// события до хука, и по её ответу хук ставится заново.
/// </remarks>
public sealed class MouseHook : IDisposable
{
    private readonly IMouseHookListener _listener;
    private readonly Native.LowLevelMouseProc _callback;   // держим ссылку живой
    private IntPtr _hook = IntPtr.Zero;

    private bool _pressing;

    private Thread? _thread;
    private uint _threadId;
    private int _startError;
    private readonly ManualResetEventSlim _started = new(false);

    // Когда хук последний раз получил событие (Environment.TickCount64).
    private long _lastEventTick;
    // Где был курсор на прошлой проверке и сколько проверок подряд хук молчал.
    private Native.POINT _checkedCursor;
    private int _silentChecks;

    /// <summary>Пауза: события проходят насквозь, как будто программы нет.</summary>
    public bool Paused { get; set; }

    /// <summary>Кнопка-модификатор: BTN_RIGHT или BTN_MIDDLE.</summary>
    public string TriggerButton { get; set; } = "BTN_RIGHT";

    public bool IsRunning => _hook != IntPtr.Zero;

    public MouseHook(IMouseHookListener listener)
    {
        _listener = listener;
        _callback = Callback;
    }

    /// <summary>Включить перехват на ОТДЕЛЬНОМ потоке с собственной очередью.</summary>
    /// <remarks>
    /// Колбэк хука приходит на тот поток, что поставил хук. Раньше это был
    /// поток интерфейса — и любая его занятость (открытый редактор, диалог,
    /// пауза сборки мусора) задерживала колбэк, а задержанный глобальный хук
    /// морозит мышь во ВСЕЙ системе, вплоть до «не снять из диспетчера». Теперь
    /// хук живёт на своём потоке и от интерфейса не зависит.
    /// </remarks>
    public void Start()
    {
        if (_thread is not null)
        {
            return;
        }
        _started.Reset();
        // Высокий приоритет: обработчик обязан успевать, даже когда процессор
        // занят перерисовкой или чужой программой.
        _thread = new Thread(Pump)
        {
            IsBackground = true,
            Name = "GlyphstrokeMouseHook",
            Priority = ThreadPriority.Highest,
        };
        _thread.SetApartmentState(ApartmentState.STA);
        _thread.Start();
        _started.Wait(3000);
        Interlocked.Exchange(ref _lastEventTick, Environment.TickCount64);
        _silentChecks = 0;
        Native.GetCursorPos(out _checkedCursor);
        if (_hook == IntPtr.Zero)
        {
            _thread = null;
            throw new InvalidOperationException(
                L.Tr("Не удалось поставить перехват мыши: ") + _startError);
        }
    }

    /// <summary>Тело потока перехвата: ставим хук и крутим очередь сообщений.</summary>
    private void Pump()
    {
        _threadId = Native.GetCurrentThreadId();
        _hook = Native.SetWindowsHookEx(Native.WH_MOUSE_LL, _callback, Native.GetModuleHandle(null), 0);
        _startError = Marshal.GetLastWin32Error();
        _started.Set();
        if (_hook == IntPtr.Zero)
        {
            return;
        }
        while (Native.GetMessage(out var msg, IntPtr.Zero, 0, 0) > 0)
        {
            Native.TranslateMessage(ref msg);
            Native.DispatchMessage(ref msg);
        }
        if (_hook != IntPtr.Zero)
        {
            Native.UnhookWindowsHookEx(_hook);
            _hook = IntPtr.Zero;
        }
    }

    public void Stop()
    {
        var thread = _thread;
        if (thread is null)
        {
            return;
        }
        _thread = null;
        if (_threadId != 0)
        {
            Native.PostThreadMessage(_threadId, Native.WM_QUIT, IntPtr.Zero, IntPtr.Zero);
        }
        thread.Join(3000);
        _threadId = 0;
        _pressing = false;
    }

    public void Dispose() => Stop();

    /// <summary>Снять хук и поставить заново.</summary>
    public void Restart()
    {
        Stop();
        Start();
    }

    /// <summary>
    /// Похоже ли, что система сняла хук. Звать раз в секунду с потока интерфейса.
    /// </summary>
    /// <remarks>
    /// Признак — курсор двигается, а до хука не доходит ни одного события. Одной
    /// такой проверки мало: курсор может переставить программа (SetCursorPos
    /// хук не видит), поэтому нужно две подряд — снятый хук сам не вернётся, а
    /// разовый перенос курсора не повторится.
    /// </remarks>
    public bool LooksDead()
    {
        if (_thread is null || !Native.GetCursorPos(out var cursor))
        {
            return false;
        }
        bool moved = cursor.X != _checkedCursor.X || cursor.Y != _checkedCursor.Y;
        _checkedCursor = cursor;
        long silentFor = Environment.TickCount64 - Interlocked.Read(ref _lastEventTick);
        if (moved && silentFor > 900)
        {
            _silentChecks++;
        }
        else if (silentFor <= 900)
        {
            _silentChecks = 0;
        }
        return _silentChecks >= 2;
    }

    private IntPtr Callback(int code, IntPtr wParam, IntPtr lParam)
    {
        // Колбэк глобального хука мыши обязан вернуться быстро и НИКОГДА не
        // бросать исключение: и то и другое подвешивает обработку мыши во всей
        // системе. Поэтому тело в try/catch, а тяжёлую работу слушатель уводит
        // в другой поток.
        Interlocked.Exchange(ref _lastEventTick, Environment.TickCount64);
        try
        {
            return Handle(code, wParam, lParam);
        }
        catch
        {
            _pressing = false;
            return Native.CallNextHookEx(_hook, code, wParam, lParam);
        }
    }

    private IntPtr Handle(int code, IntPtr wParam, IntPtr lParam)
    {
        if (code < 0)
        {
            return Native.CallNextHookEx(_hook, code, wParam, lParam);
        }

        var data = Marshal.PtrToStructure<Native.MSLLHOOKSTRUCT>(lParam);
        if (Paused || data.ExtraInfo == Native.SelfSentMark)
        {
            return Native.CallNextHookEx(_hook, code, wParam, lParam);
        }

        int message = (int)wParam;
        var point = new Point(data.Point.X, data.Point.Y);

        if (message == DownMessage)
        {
            // Спрашиваем слушателя, наш ли это случай. Если нет (исключённая
            // программа, полноэкранное) — отдаём нажатие программе как есть,
            // ничего не глотаем и не подменяем.
            if (_listener.StrokeBegan(point))
            {
                _pressing = true;
                return new IntPtr(1);        // наш росчерк: решим на отпускании
            }
            _pressing = false;
            return Native.CallNextHookEx(_hook, code, wParam, lParam);
        }

        if (message == Native.WM_MOUSEMOVE)
        {
            if (_pressing)
            {
                _listener.StrokeExtended(point);
            }
            // Движение курсора пропускаем всегда: съесть его значит приморозить
            // указатель — рисовать станет нечем.
            return Native.CallNextHookEx(_hook, code, wParam, lParam);
        }

        if (message == UpMessage)
        {
            if (!_pressing)
            {
                return Native.CallNextHookEx(_hook, code, wParam, lParam);
            }
            _pressing = false;
            bool swallowed = _listener.StrokeEnded(point);
            if (!swallowed)
            {
                // Жеста не вышло — возвращаем программе обычный щелчок кнопкой-
                // модификатором. НЕ отсюда: щелчок, посланный SendInput, сам
                // идёт через этот же хук, а он ждёт, пока мы вернёмся. Windows
                // дожидается тайм-аута и снимает хук — программа на пару секунд
                // переставала видеть мышь после каждого неопознанного росчерка.
                // Поэтому щелчок уходит из другого потока, когда колбэк уже вернулся.
                uint down = DownFlag, up = UpFlag;
                ThreadPool.QueueUserWorkItem(_ => ReplayClick(down, up));
            }
            return new IntPtr(1);
        }

        return Native.CallNextHookEx(_hook, code, wParam, lParam);
    }

    /// <summary>Отправить системе щелчок кнопкой-модификатором.</summary>
    /// <remarks>
    /// Щелчок уходит туда, где сейчас курсор (там, где кнопку отпустили).
    /// Возвращать курсор к точке нажатия нельзя: этот прыжок туда-обратно
    /// человек видит как дёрганье указателя. Звать только НЕ с потока хука.
    /// </remarks>
    private static void ReplayClick(uint downFlag, uint upFlag)
    {
        SendMouse(downFlag);
        SendMouse(upFlag);
    }

    private static void SetCursor(Native.POINT point) => SetCursorPos(point.X, point.Y);

    [DllImport("user32.dll")]
    private static extern bool SetCursorPos(int x, int y);

    private static void SendMouse(uint flags, uint data = 0)
    {
        var input = new Native.INPUT
        {
            Type = Native.INPUT_MOUSE,
            Data = new Native.INPUTUNION
            {
                Mouse = new Native.MOUSEINPUT
                {
                    Flags = flags,
                    MouseData = data,
                    ExtraInfo = Native.SelfSentMark,
                },
            },
        };
        Native.SendInput(1, new[] { input }, Marshal.SizeOf<Native.INPUT>());
    }

    // --- какая кнопка выбрана ---

    private bool Middle => string.Equals(TriggerButton, "BTN_MIDDLE", StringComparison.OrdinalIgnoreCase);

    private int DownMessage => Middle ? Native.WM_MBUTTONDOWN : Native.WM_RBUTTONDOWN;

    private int UpMessage => Middle ? Native.WM_MBUTTONUP : Native.WM_RBUTTONUP;

    private uint DownFlag => Middle ? Native.MOUSEEVENTF_MIDDLEDOWN : Native.MOUSEEVENTF_RIGHTDOWN;

    private uint UpFlag => Middle ? Native.MOUSEEVENTF_MIDDLEUP : Native.MOUSEEVENTF_RIGHTUP;
}
