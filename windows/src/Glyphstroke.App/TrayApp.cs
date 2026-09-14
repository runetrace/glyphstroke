using System.IO;
using System.Diagnostics;
using System.Drawing;
using System.Reflection;
using System.Windows;
using System.Windows.Forms;
using Microsoft.Win32;
using Glyphstroke.Core;
using Application = System.Windows.Application;
using MessageBox = System.Windows.MessageBox;

namespace Glyphstroke.App;

/// <summary>Значок в области уведомлений и всё, что вокруг него.</summary>
/// <remarks>
/// Значок обязателен. Невидимая программа, которая перехватывает мышь,
/// выглядит поломкой системы: человеку нужно одним движением увидеть, работает
/// она сейчас или на паузе, и одним же движением её выключить.
///
/// Перехват ставится на этом же потоке — на том, где крутится очередь сообщений
/// окна. Так задумано: обработчик хука вызывается системой именно в нём, и
/// обращения к следу из него выполняются напрямую, без ожидания другого потока.
/// Хук обязан возвращаться за доли секунды, и лишнее ожидание здесь было бы
/// прямой дорогой к тому, что Windows выбросит его из цепочки.
/// </remarks>
public sealed class TrayApp : IDisposable
{
    private readonly Store _store = new();
    private readonly NotifyIcon _icon = new();
    private TrailWindow _trail = null!;
    private GestureEngine _engine = null!;
    private EditorWindow? _editor;
    private HelpWindow? _help;
    private SettingsWindow? _settings;
    private readonly List<string> _log = new();
    private System.Windows.Forms.Timer? _updateTimer;

    public static string Version =>
        Assembly.GetExecutingAssembly().GetName().Version is { } version
            ? $"{version.Major}.{version.Minor}.{version.Build}"
            : "0";

    public void Start()
    {
        var settings = _store.LoadSettings();
        L.Use(settings.Language);
        _store.ActiveProfile = settings.ActiveProfile;
        InstallStarterGestures();

        _trail = new TrailWindow(_store.LoadSettings().Overlay);
        // Окно нужно создать заранее, чтобы у него появился дескриптор: иначе
        // первый же росчерк тратил бы время на создание окна прямо в хуке.
        // Окно следа показываем один раз и держим показанным: оно сквозное и
        // пустое, поэтому невидимо, зато не мерцает при каждом росчерке.
        _trail.Show();

        _engine = new GestureEngine(_store, _trail) { OnLog = Append };
        BuildIcon();

        try
        {
            _engine.Start();
        }
        catch (Exception exception)
        {
            Append("перехват не включился: " + exception.Message);
            MessageBox.Show(L.Tr("Не удалось включить перехват мыши:\n\n") + exception.Message,
                            "Glyphstroke", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        RefreshMenu();
        StartUpdateChecks();
    }

    public void Dispose()
    {
        _updateTimer?.Dispose();
        _engine?.Dispose();
        _icon.Visible = false;
        _icon.Dispose();
    }

    // --- значок ---

    private void BuildIcon()
    {
        _icon.Icon = LoadIcon();
        _icon.Text = "Glyphstroke";
        _icon.Visible = true;
        _icon.DoubleClick += (_, _) => ShowEditor();
        RefreshMenu();
    }

    private static Icon LoadIcon()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "glyphstroke.ico");
        return File.Exists(path) ? new Icon(path) : SystemIcons.Application;
    }

    private void RefreshMenu()
    {
        var menu = new ContextMenuStrip();

        string state = _engine.Paused ? L.Tr("На паузе")
            : _engine.IsRunning ? $"{L.Tr("Жестов загружено:")} {_engine.GestureCount}"
            : L.Tr("Перехват не включён");
        menu.Items.Add(new ToolStripMenuItem(state) { Enabled = false });
        menu.Items.Add(new ToolStripSeparator());

        menu.Items.Add(new ToolStripMenuItem(_engine.Paused ? L.Tr("Продолжить") : L.Tr("Пауза"), null,
            (_, _) => { _engine.Paused = !_engine.Paused; RefreshMenu(); }));
        menu.Items.Add(new ToolStripMenuItem(L.Tr("Жесты…"), null, (_, _) => ShowEditor()));
        menu.Items.Add(new ToolStripMenuItem(L.Tr("Настройки…"), null, (_, _) => ShowSettings()));
        menu.Items.Add(new ToolStripMenuItem(L.Tr("Журнал…"), null, (_, _) => ShowLog()));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem(L.Tr("Проверить обновления…"), null, (_, _) => CheckUpdates(force: true)));
        menu.Items.Add(new ToolStripMenuItem(L.Tr("Справка…"), null, (_, _) => ShowHelp()));
        menu.Items.Add(new ToolStripMenuItem(L.Tr("О программе…"), null, (_, _) => ShowAbout()));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem(L.Tr("Выйти"), null, (_, _) => Application.Current.Shutdown()));

        _icon.ContextMenuStrip = menu;
    }

    // --- окна ---

    private void ShowHelp()
    {
        if (_help is null || !_help.IsLoaded)
        {
            _help = new HelpWindow();
            _help.Closed += (_, _) => _help = null;
        }
        _help.Show();
        _help.Activate();
    }

    /// <summary>Показать окно программы — например, на повторный запуск из ярлыка.</summary>
    public void ShowMainWindow() => ShowEditor();

    private void ShowEditor()
    {
        if (_editor is null || !_editor.IsLoaded)
        {
            _editor = new EditorWindow(_store, () =>
            {
                _engine.Reload();
                RefreshMenu();
            });
        }
        _editor.ReloadFromDisk();
        _editor.Show();
        _editor.Activate();
    }

    private void ShowSettings()
    {
        if (_settings is null || !_settings.IsLoaded)
        {
            _settings = new SettingsWindow(_store, () =>
            {
                _engine.Reload();
                _trail.Settings = _store.LoadSettings().Overlay;
                RefreshMenu();
            });
        }
        _settings.Show();
        _settings.Activate();
    }

    private void ShowAbout()
    {
        MessageBox.Show(
            $"Glyphstroke {Version}\n\n" + L.Tr("Управление устройством жестами.\n\n")
            + L.Tr("Вопросы и сообщения об ошибках: runetrace@proton.me"),
            L.Tr("О программе"), MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private void ShowLog()
    {
        string path = Path.Combine(Path.GetTempPath(), L.Tr("glyphstroke-журнал.txt"));
        File.WriteAllText(path, string.Join(Environment.NewLine, _log));
        Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    }

    private void Append(string message)
    {
        _log.Add($"{DateTime.Now:HH:mm:ss}  {message}");
        // Журнал нужен для разбора «почему не сработало», а не для истории:
        // держим последние двести строк и не растём в памяти.
        if (_log.Count > 200)
        {
            _log.RemoveRange(0, _log.Count - 200);
        }
    }

    // --- стартовый набор ---

    private void InstallStarterGestures()
    {
        string directory = Path.Combine(AppContext.BaseDirectory, "gestures");
        int copied = _store.InstallStarterGestures(directory);
        if (copied > 0)
        {
            Append($"положен стартовый набор жестов: {copied}");
        }
    }

    // --- обновления ---

    /// <summary>
    /// Раз в сутки узнавать, не вышла ли версия новее. Ставит человек сам —
    /// программа держит мышь, и подменять её за спиной нельзя.
    /// </summary>
    private void StartUpdateChecks()
    {
        _updateTimer = new System.Windows.Forms.Timer { Interval = (int)UpdateCheck.Interval.TotalMilliseconds };
        _updateTimer.Tick += (_, _) => CheckUpdates(force: false);
        _updateTimer.Start();

        // Первый запрос с задержкой: при входе в систему сеть обычно ещё не
        // поднялась, да и мешать старту незачем.
        var delay = new System.Windows.Forms.Timer { Interval = 30_000 };
        delay.Tick += (_, _) =>
        {
            delay.Stop();
            delay.Dispose();
            CheckUpdates(force: false);
        };
        delay.Start();
    }

    private async void CheckUpdates(bool force)
    {
        var settings = _store.LoadSettings();
        if (!force && !settings.CheckUpdates)
        {
            return;
        }
        if (!force && !UpdateCheck.Due(_store))
        {
            OfferPending(settings);
            return;
        }

        string repository = UpdateCheck.Repository(settings);
        // Сравниваем с версией нашего установщика в релизе, а не с общим тегом:
        // тег уходит вперёд из-за выпусков под Linux/macOS.
        var release = await UpdateCheck.FetchAsync(repository, Version, "-setup.exe").ConfigureAwait(true);
        UpdateCheck.Remember(_store, release);

        if (release is not null && UpdateCheck.IsNewer(release.Version, Version))
        {
            Append($"вышла версия {release.Version}, установлена {Version}");
            Offer(release, repository);
        }
        else if (force)
        {
            MessageBox.Show($"{L.Tr("Установлена последняя версия")} {Version}.\n\n"
                            + L.Tr("Новых выпусков нет — или сервер не ответил."),
                            L.Tr("Обновления"), MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void OfferPending(Settings settings)
    {
        var release = UpdateCheck.Pending(_store, Version);
        if (release is not null)
        {
            Offer(release, UpdateCheck.Repository(settings));
        }
    }

    private void Offer(ReleaseInfo release, string repository)
    {
        string notes = release.Notes.Length == 0
            ? string.Empty
            : "\n\n" + release.Notes[..Math.Min(600, release.Notes.Length)];
        var answer = MessageBox.Show(
            $"{L.Tr("Вышла версия")} {release.Version}, {L.Tr("установлена")} {Version}.\n\n"
            + L.Tr("Обновление ставится вручную: программа не заменяет себя сама.")
            + notes + L.Tr("\n\nОткрыть страницу загрузки?"),
            L.Tr("Обновление"), MessageBoxButton.YesNo, MessageBoxImage.Information);
        if (answer == MessageBoxResult.Yes)
        {
            string url = release.Url.Length > 0 ? release.Url : UpdateCheck.ReleasePage(repository);
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
        }
    }

    // --- автозапуск ---

    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

    /// <summary>
    /// Запускается ли программа при входе. Запись в реестре, а не ярлык в папке
    /// «Автозагрузка»: ярлык человек случайно уносит вместе с папкой, а запись
    /// переживает и перенос программы, если её поправить.
    /// </summary>
    public static bool LaunchesAtLogin()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunKey);
        return key?.GetValue("Glyphstroke") is string value && value.Length > 0;
    }

    public static void SetLaunchAtLogin(bool enabled)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        if (key is null)
        {
            return;
        }
        if (enabled)
        {
            string path = Environment.ProcessPath ?? Assembly.GetExecutingAssembly().Location;
            key.SetValue("Glyphstroke", $"\"{path}\"");
        }
        else
        {
            key.DeleteValue("Glyphstroke", throwOnMissingValue: false);
        }
    }
}
