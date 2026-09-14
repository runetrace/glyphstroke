using System.Diagnostics;
using System.Runtime.InteropServices;
using Glyphstroke.Core;

namespace Glyphstroke.App;

/// <summary>Выполнение действий жеста.</summary>
/// <remarks>
/// Набор типов общий с версиями для Linux и macOS, меняется только исполнение:
/// клавиши и щелчки уходят через SendInput, окна слушаются ShowWindow и
/// WM_CLOSE, программы запускает оболочка.
///
/// Всё выполняется в отдельном потоке: перехватчик обязан вернуть ответ за доли
/// секунды, иначе Windows выкинет его из цепочки, а действие жеста может и
/// подождать, и запустить программу, и поспать по «паузе».
/// </remarks>
public sealed class ActionRunner
{
    public Action<string>? OnLog { get; set; }

    public void Run(IReadOnlyList<GestureAction> actions)
    {
        if (actions.Count == 0)
        {
            return;
        }
        var copy = actions.ToList();
        Task.Run(() =>
        {
            foreach (var action in copy)
            {
                try
                {
                    RunOne(action);
                }
                catch (Exception exception)
                {
                    Log($"действие «{action.Type}» ({action.Value}) не выполнено: {exception.Message}");
                }
            }
        });
    }

    private void RunOne(GestureAction action)
    {
        switch (action.Type)
        {
            case "standard": RunStandard(action.Value); break;
            case "keys": SendKeys(action.Value); break;
            case "text": SendText(action.Value); break;
            case "command": RunCommand(action.Value); break;
            case "app": OpenApp(action.Value); break;
            case "button": ClickButton(action.Value); break;
            case "scroll": Scroll(action.Value); break;
            case "window": WindowCommand(action.Value); break;
            case "delay": Thread.Sleep(Math.Max(0, ParseInt(action.Value))); break;
            case "none":
            case "": break;
            default: Log($"неизвестный тип действия: {action.Type}"); break;
        }
    }

    /// <summary>Стандартное действие системы: разворачиваем имя и выполняем.</summary>
    /// <remarks>
    /// Разворот здесь, а не при чтении файла, намеренно: в файле жеста остаётся
    /// имя, и тот же файл на другой системе выполнит её собственное сочетание.
    /// </remarks>
    private void RunStandard(string value)
    {
        var action = StandardActions.Find(value);
        if (action is null)
        {
            Log($"не знаю такого стандартного действия: {value}");
            return;
        }
        if (action.Kind == StandardKind.Keys)
        {
            SendKeys(action.Value);
        }
        else
        {
            WindowCommand(action.Value);
        }
    }

    // --- клавиши и текст ---

    private void SendKeys(string value)
    {
        // Несколько сочетаний подряд пишутся через пробел: «ctrl+c ctrl+v».
        foreach (var part in value.Split(' ', StringSplitOptions.RemoveEmptyEntries))
        {
            if (!KeyMap.TryParse(part, out var keys))
            {
                Log($"не понял сочетание клавиш: {part}");
                return;
            }
            var inputs = new List<Native.INPUT>();
            foreach (var key in keys)
            {
                inputs.Add(KeyInput(key, down: true));
            }
            for (int i = keys.Count - 1; i >= 0; i--)
            {
                inputs.Add(KeyInput(keys[i], down: false));
            }
            Native.SendInput((uint)inputs.Count, inputs.ToArray(), Marshal.SizeOf<Native.INPUT>());
        }
    }

    private void SendText(string value)
    {
        if (value.Length == 0)
        {
            return;
        }
        // Символы отправляются как есть, без обращения к раскладке: так
        // печатается и кириллица, и то, чего на клавиатуре вовсе нет.
        var inputs = new List<Native.INPUT>();
        foreach (char symbol in value)
        {
            inputs.Add(UnicodeInput(symbol, down: true));
            inputs.Add(UnicodeInput(symbol, down: false));
        }
        Native.SendInput((uint)inputs.Count, inputs.ToArray(), Marshal.SizeOf<Native.INPUT>());
    }

    private static Native.INPUT KeyInput(ushort virtualKey, bool down) => new()
    {
        Type = Native.INPUT_KEYBOARD,
        Data = new Native.INPUTUNION
        {
            Keyboard = new Native.KEYBDINPUT
            {
                VirtualKey = virtualKey,
                Flags = down ? 0 : Native.KEYEVENTF_KEYUP,
                ExtraInfo = Native.SelfSentMark,
            },
        },
    };

    private static Native.INPUT UnicodeInput(char symbol, bool down) => new()
    {
        Type = Native.INPUT_KEYBOARD,
        Data = new Native.INPUTUNION
        {
            Keyboard = new Native.KEYBDINPUT
            {
                ScanCode = symbol,
                Flags = Native.KEYEVENTF_UNICODE | (down ? 0 : Native.KEYEVENTF_KEYUP),
                ExtraInfo = Native.SelfSentMark,
            },
        },
    };

    // --- программы ---

    private void RunCommand(string value)
    {
        string command = value.Trim();
        if (command.Length == 0)
        {
            return;
        }
        Process.Start(new ProcessStartInfo("cmd.exe", "/c " + command)
        {
            CreateNoWindow = true,
            UseShellExecute = false,
        });
    }

    /// <summary>Запустить программу: по имени, по пути или по ярлыку.</summary>
    private void OpenApp(string value)
    {
        string name = value.Trim();
        if (name.Length == 0)
        {
            return;
        }
        // UseShellExecute даёт то же, что двойной щелчок в проводнике: найдётся
        // и «notepad», и путь к .exe, и ярлык, и даже папка.
        Process.Start(new ProcessStartInfo(name) { UseShellExecute = true });
    }

    // --- мышь ---

    private void ClickButton(string value)
    {
        string name = value.Trim().ToLowerInvariant();
        (uint down, uint up) = name switch
        {
            "middle" or "btn_middle" => (Native.MOUSEEVENTF_MIDDLEDOWN, Native.MOUSEEVENTF_MIDDLEUP),
            "right" or "btn_right" => (Native.MOUSEEVENTF_RIGHTDOWN, Native.MOUSEEVENTF_RIGHTUP),
            _ => (Native.MOUSEEVENTF_LEFTDOWN, Native.MOUSEEVENTF_LEFTUP),
        };
        SendMouse(down);
        SendMouse(up);
    }

    /// <summary><c>up</c>, <c>down 3</c>, <c>left 2</c> — прокрутка на несколько щелчков.</summary>
    private void Scroll(string value)
    {
        var parts = value.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        string direction = parts.Length > 0 ? parts[0].ToLowerInvariant() : "down";
        int amount = parts.Length > 1 ? ParseInt(parts[1], 1) : 1;
        const int step = 120;               // один «щелчок» колеса

        switch (direction)
        {
            case "up": SendMouse(Native.MOUSEEVENTF_WHEEL, (uint)(step * amount)); break;
            case "down": SendMouse(Native.MOUSEEVENTF_WHEEL, unchecked((uint)(-step * amount))); break;
            case "right": SendMouse(Native.MOUSEEVENTF_HWHEEL, (uint)(step * amount)); break;
            case "left": SendMouse(Native.MOUSEEVENTF_HWHEEL, unchecked((uint)(-step * amount))); break;
            default: SendMouse(Native.MOUSEEVENTF_WHEEL, unchecked((uint)(-step * amount))); break;
        }
    }

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

    // --- окна ---

    /// <summary>minimize | maximize | unmaximize | close | activate.</summary>
    private void WindowCommand(string value)
    {
        string command = value.Trim().ToLowerInvariant();
        IntPtr window = Native.GetForegroundWindow();
        if (window == IntPtr.Zero)
        {
            Log(L.Tr("не вижу активного окна"));
            return;
        }

        switch (command)
        {
            case "minimize" or "":
                Native.ShowWindow(window, Native.SW_MINIMIZE);
                break;
            case "maximize":
                Native.ShowWindow(window, Native.SW_MAXIMIZE);
                break;
            case "unmaximize" or "restore":
                Native.ShowWindow(window, Native.SW_RESTORE);
                break;
            case "close":
                // WM_CLOSE, а не завершение процесса: программа успеет спросить
                // про несохранённое.
                Native.PostMessage(window, Native.WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
                break;
            case "activate":
                Native.SetForegroundWindow(window);
                break;
            default:
                Log($"не знаю такого действия над окном: {command}");
                break;
        }
    }

    private static int ParseInt(string value, int fallback = 0) =>
        int.TryParse(value.Trim(), out int result) ? result : fallback;

    private void Log(string message) => OnLog?.Invoke(message);
}
