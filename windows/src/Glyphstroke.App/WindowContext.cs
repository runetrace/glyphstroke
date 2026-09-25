using System.Diagnostics;
using Glyphstroke.Core;

namespace Glyphstroke.App;

/// <summary>Кто сейчас впереди: по этому жест решает, работать ему или нет.</summary>
/// <remarks>
/// Строка собирается в том же виде, что на других системах, — «программа |
/// заголовок окна», — потому что фильтры в файлах жестов сверяются именно с
/// ней. Первая половина здесь — имя исполняемого файла (<c>chrome.exe</c>): на
/// Linux это класс окна, на маке идентификатор пакета.
///
/// Никаких разрешений, в отличие от мака, не нужно: Windows отдаёт и заголовок
/// окна, и имя процесса любому желающему.
/// </remarks>
public static class WindowContext
{
    /// <summary>Сколько доверять последнему ответу: опрос идёт на каждом росчерке.</summary>
    private static readonly TimeSpan CacheTtl = TimeSpan.FromMilliseconds(250);

    private static string? _cached;
    private static DateTime _cachedAt = DateTime.MinValue;

    public static string? Current()
    {
        if (_cached is not null && DateTime.UtcNow - _cachedAt < CacheTtl)
        {
            return _cached;
        }
        _cached = Read();
        _cachedAt = DateTime.UtcNow;
        return _cached;
    }

    public static void Forget()
    {
        _cached = null;
        _cachedAt = DateTime.MinValue;
    }

    private static string? Read()
    {
        IntPtr window = Native.GetForegroundWindow();
        if (window == IntPtr.Zero)
        {
            return null;
        }

        string process = ProcessName(window);
        string title = WindowTitle(window);
        if (process.Length == 0)
        {
            return title.Length == 0 ? null : title;
        }
        return title.Length == 0 ? process : $"{process} | {title}";
    }

    /// <summary>Верхнеуровневое окно под точкой экрана — цель жеста.</summary>
    /// <remarks>
    /// Действие жеста применяется к окну, над которым НАЧАЛСЯ росчерк, а не к
    /// тому, что было активным: перехватчик глотает нажатие правой кнопки, и
    /// окно под курсором само на передний план не выходит, поэтому цель надо
    /// определить по точке начала.
    /// </remarks>
    internal static IntPtr WindowUnder(int x, int y)
    {
        IntPtr window = Native.WindowFromPoint(new Native.POINT { X = x, Y = y });
        if (window == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }
        IntPtr root = Native.GetAncestor(window, Native.GA_ROOT);
        return root == IntPtr.Zero ? window : root;
    }

    /// <summary>Имя процесса окна под точкой экрана — для мишени выбора программы.</summary>
    internal static string? ProcessUnder(Native.POINT point)
    {
        IntPtr window = Native.WindowFromPoint(point);
        if (window == IntPtr.Zero)
        {
            return null;
        }
        IntPtr root = Native.GetAncestor(window, Native.GA_ROOT);
        string name = ProcessName(root == IntPtr.Zero ? window : root);
        return name.Length == 0 ? null : name;
    }

    private static string ProcessName(IntPtr window)
    {
        try
        {
            Native.GetWindowThreadProcessId(window, out uint processId);
            if (processId == 0)
            {
                return string.Empty;
            }
            using var process = Process.GetProcessById((int)processId);
            // Имя без пути и с расширением: так его и пишут в фильтрах —
            // «class:chrome.exe».
            return process.ProcessName + ".exe";
        }
        catch (Exception)
        {
            // Процесс мог закрыться между запросом и чтением — это не ошибка.
            return string.Empty;
        }
    }

    private static string WindowTitle(IntPtr window)
    {
        var buffer = new char[512];
        int length = Native.GetWindowTextW(window, buffer, buffer.Length);
        return length > 0 ? new string(buffer, 0, length) : string.Empty;
    }

    /// <summary>
    /// Развёрнуто ли активное окно во весь экран — для настройки «отключаться в
    /// полноэкранных».
    /// </summary>
    /// <remarks>
    /// Проверяем не «развёрнуто на весь монитор», а «занимает монитор целиком,
    /// вместе с панелью задач»: именно так ведут себя игры и полноэкранное
    /// видео, а обычное развёрнутое окно оставляет панель видимой.
    /// </remarks>
    public static bool IsFullscreen()
    {
        IntPtr window = Native.GetForegroundWindow();
        if (window == IntPtr.Zero || !Native.GetWindowRect(window, out var rect))
        {
            return false;
        }
        IntPtr monitor = Native.MonitorFromWindow(window, Native.MONITOR_DEFAULTTONEAREST);
        var info = new Native.MONITORINFO { Size = System.Runtime.InteropServices.Marshal.SizeOf<Native.MONITORINFO>() };
        if (!Native.GetMonitorInfoW(monitor, ref info))
        {
            return false;
        }
        // Допуск в пару пикселей: часть игр отдаёт рамку на 1–2 px больше/меньше
        // монитора, и строгое равенство иногда не срабатывало.
        const int slack = 2;
        var m = info.Monitor;
        return rect.Left <= m.Left + slack && rect.Top <= m.Top + slack
            && rect.Right >= m.Right - slack && rect.Bottom >= m.Bottom - slack;
    }
}
