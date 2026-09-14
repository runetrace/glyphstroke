using System.Runtime.InteropServices;
using Glyphstroke.Core;

namespace Glyphstroke.App;

/// <summary>Кому перехватчик рассказывает о росчерке.</summary>
public interface IMouseHookListener
{
    void StrokeBegan(Point point);
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
/// </remarks>
public sealed class MouseHook : IDisposable
{
    private readonly IMouseHookListener _listener;
    private readonly Native.LowLevelMouseProc _callback;   // держим ссылку живой
    private IntPtr _hook = IntPtr.Zero;

    private bool _pressing;
    private Native.POINT _pressLocation;

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

    /// <summary>Включить перехват. Ставится на поток с очередью сообщений.</summary>
    public void Start()
    {
        if (_hook != IntPtr.Zero)
        {
            return;
        }
        _hook = Native.SetWindowsHookEx(Native.WH_MOUSE_LL, _callback, Native.GetModuleHandle(null), 0);
        if (_hook == IntPtr.Zero)
        {
            throw new InvalidOperationException(
                L.Tr("Не удалось поставить перехват мыши: ") + Marshal.GetLastWin32Error());
        }
    }

    public void Stop()
    {
        if (_hook != IntPtr.Zero)
        {
            Native.UnhookWindowsHookEx(_hook);
            _hook = IntPtr.Zero;
        }
        _pressing = false;
    }

    public void Dispose() => Stop();

    private IntPtr Callback(int code, IntPtr wParam, IntPtr lParam)
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
            _pressing = true;
            _pressLocation = data.Point;
            _listener.StrokeBegan(point);
            return new IntPtr(1);            // нажатие забираем: решим на отпускании
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
                // Жеста не вышло — возвращаем программе обычный щелчок в той
                // точке, где кнопку нажали, а не там, где отпустили: иначе меню
                // открылось бы в стороне от места нажатия.
                ReplayClick(_pressLocation);
            }
            return new IntPtr(1);
        }

        return Native.CallNextHookEx(_hook, code, wParam, lParam);
    }

    /// <summary>Отправить системе щелчок кнопкой-модификатором.</summary>
    /// <summary>Отправить системе щелчок кнопкой-модификатором.</summary>
    /// <remarks>
    /// Щелчок уходит туда, где сейчас курсор (там, где кнопку отпустили).
    /// Возвращать курсор к точке нажатия нельзя: этот прыжок туда-обратно
    /// человек видит как дёрганье указателя.
    /// </remarks>
    private void ReplayClick(Native.POINT where)
    {
        SendMouse(DownFlag);
        SendMouse(UpFlag);
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
