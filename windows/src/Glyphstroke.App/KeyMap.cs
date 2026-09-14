namespace Glyphstroke.App;

/// <summary>
/// Разбор записи вроде <c>ctrl+shift+t</c> в коды виртуальных клавиш Windows.
/// </summary>
/// <remarks>
/// Имена принимаются и в здешнем виде, и в том, что лежит в файлах жестов от
/// Linux и macOS (<c>Page_Up</c>, <c>bracketleft</c>, <c>cmd</c>): файлы у трёх
/// версий общие, и запись, перенесённая с другой машины, должна хотя бы
/// разбираться. А вот сами сочетания перенести нельзя, и подменять их за спиной
/// человека нельзя тем более — для этого есть тип действия «стандартное».
/// </remarks>
public static class KeyMap
{
    private static readonly Dictionary<string, ushort> Keys = new(StringComparer.OrdinalIgnoreCase)
    {
        // модификаторы
        ["ctrl"] = 0x11, ["control"] = 0x11,
        ["alt"] = 0x12, ["option"] = 0x12, ["opt"] = 0x12,
        ["shift"] = 0x10,
        ["win"] = 0x5B, ["super"] = 0x5B, ["meta"] = 0x5B, ["cmd"] = 0x5B, ["command"] = 0x5B,

        // управление
        ["enter"] = 0x0D, ["return"] = 0x0D,
        ["tab"] = 0x09, ["space"] = 0x20,
        ["backspace"] = 0x08,
        ["delete"] = 0x2E, ["del"] = 0x2E, ["forwarddelete"] = 0x2E,
        ["escape"] = 0x1B, ["esc"] = 0x1B,
        ["insert"] = 0x2D, ["ins"] = 0x2D,
        ["home"] = 0x24, ["end"] = 0x23,
        ["pageup"] = 0x21, ["page_up"] = 0x21, ["pgup"] = 0x21, ["prior"] = 0x21,
        ["pagedown"] = 0x22, ["page_down"] = 0x22, ["pgdn"] = 0x22, ["next"] = 0x22,
        ["left"] = 0x25, ["up"] = 0x26, ["right"] = 0x27, ["down"] = 0x28,
        ["printscreen"] = 0x2C, ["print"] = 0x2C, ["prtsc"] = 0x2C,
        ["capslock"] = 0x14, ["menu"] = 0x5D, ["apps"] = 0x5D,

        // знаки: имена в стиле X11 — в перенесённых файлах встречаются именно они
        ["minus"] = 0xBD, ["-"] = 0xBD,
        ["equal"] = 0xBB, ["="] = 0xBB, ["plus"] = 0xBB,
        ["bracketleft"] = 0xDB, ["["] = 0xDB,
        ["bracketright"] = 0xDD, ["]"] = 0xDD,
        ["backslash"] = 0xDC, ["\\"] = 0xDC,
        ["semicolon"] = 0xBA, [";"] = 0xBA,
        ["apostrophe"] = 0xDE, ["'"] = 0xDE,
        ["grave"] = 0xC0, ["`"] = 0xC0,
        ["comma"] = 0xBC, [","] = 0xBC,
        ["period"] = 0xBE, ["."] = 0xBE,
        ["slash"] = 0xBF, ["/"] = 0xBF,
    };

    static KeyMap()
    {
        for (char letter = 'a'; letter <= 'z'; letter++)
        {
            Keys[letter.ToString()] = (ushort)char.ToUpperInvariant(letter);
        }
        for (char digit = '0'; digit <= '9'; digit++)
        {
            Keys[digit.ToString()] = digit;
        }
        for (int number = 1; number <= 24; number++)
        {
            Keys["f" + number] = (ushort)(0x70 + number - 1);
        }
    }

    /// <summary>
    /// <c>ctrl+shift+t</c> → коды клавиш по порядку нажатия; отпускаются они в
    /// обратном.
    /// </summary>
    public static bool TryParse(string combination, out List<ushort> keys)
    {
        keys = new List<ushort>();
        var parts = combination.Split('+', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0)
        {
            return false;
        }

        var modifiers = new List<ushort>();
        ushort? main = null;
        foreach (var raw in parts)
        {
            string name = raw.Trim();
            if (name.Length == 0)
            {
                continue;
            }
            if (!Keys.TryGetValue(name, out ushort code))
            {
                return false;
            }
            if (IsModifier(code))
            {
                modifiers.Add(code);
            }
            else if (main is null)
            {
                main = code;
            }
            else
            {
                // «ctrl+a+b» — это опечатка, и нажать половину хуже, чем ничего.
                return false;
            }
        }

        if (main is null && modifiers.Count == 0)
        {
            return false;
        }
        keys.AddRange(modifiers);
        if (main is not null)
        {
            keys.Add(main.Value);
        }
        return true;
    }

    private static bool IsModifier(ushort code) => code is 0x11 or 0x12 or 0x10 or 0x5B or 0x5C;
}
