using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using Glyphstroke.Core;

namespace Glyphstroke.App;

/// <summary>Настройки: кнопка-модификатор, распознавание, след, автозапуск.</summary>
/// <remarks>
/// Здесь, в отличие от редактора жестов, есть кнопка «Применить». Разница не в
/// прихоти: правка настройки перезапускает перехват и перерисовывает след, и
/// делать это на каждую букву, набранную в поле, было бы дёргано.
/// </remarks>
public sealed class SettingsWindow : Window
{
    private readonly Store _store;
    private readonly Action _changed;
    private readonly Settings _settings;

    private readonly ComboBox _trigger = new() { Width = 220 };
    private readonly Slider _minStroke = new() { Width = 220, Minimum = 10, Maximum = 150, TickFrequency = 5, IsSnapToTickEnabled = true };
    private readonly TextBlock _minStrokeLabel = new();
    private readonly ComboBox _unrecognized = new() { Width = 220 };
    private readonly CheckBox _fullscreen = new() { Content = L.Tr("Отключаться в полноэкранных") };
    private AppListEditor _excludedEditor = null!;

    private readonly CheckBox _trailEnabled = new() { Content = L.Tr("Рисовать след") };
    private readonly TextBox _trailColor = new() { Width = 100 };
    private readonly Rectangle _trailSample = new() { Width = 60, Height = 18, Margin = new Thickness(8, 0, 0, 0) };
    private readonly Slider _trailWidth = new() { Width = 220, Minimum = 1, Maximum = 12, TickFrequency = 1, IsSnapToTickEnabled = true };
    private readonly Slider _trailOpacity = new() { Width = 220, Minimum = 10, Maximum = 100, TickFrequency = 5, IsSnapToTickEnabled = true };
    private readonly Slider _trailFade = new() { Width = 220, Minimum = 0, Maximum = 1000, TickFrequency = 20, IsSnapToTickEnabled = true };

    private readonly CheckBox _autostart = new() { Content = L.Tr("Запускать при входе в систему") };
    private readonly CheckBox _checkUpdates = new() { Content = L.Tr("Проверять обновления") };
    private readonly TextBox _updateRepo = new() { Width = 220 };
    private readonly ComboBox _theme = new() { Width = 220 };
    private readonly ComboBox _language = new() { Width = 220 };

    public SettingsWindow(Store store, Action changed)
    {
        _store = store;
        _changed = changed;
        _settings = store.LoadSettings();

        Title = L.Tr("Glyphstroke — настройки");
        Width = 520;
        Height = 640;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        this.SetResourceReference(BackgroundProperty, "RcWindow");
        SourceInitialized += (_, _) => Theme.ApplyWindowChrome(this);
        _excludedEditor = new AppListEditor(() => { }, L.Tr("Пусто — жесты работают во всех программах."));
        Content = BuildLayout();
        Fill();
        // Подписываемся после Fill, чтобы начальный выбор не считался за смену:
        // тема применяется вживую только когда её меняет человек.
        _theme.SelectionChanged += (_, _) =>
        {
            if (_theme.SelectedItem is ComboBoxItem item)
            {
                Theme.SetTheme((string)item.Tag);
            }
        };
    }

    private UIElement BuildLayout()
    {
        var panel = new StackPanel { Margin = new Thickness(16) };

        _trigger.Items.Add(new ComboBoxItem { Content = L.Tr("Правая кнопка"), Tag = "BTN_RIGHT" });
        _trigger.Items.Add(new ComboBoxItem { Content = L.Tr("Средняя кнопка"), Tag = "BTN_MIDDLE" });
        var strokeRow = new StackPanel { Orientation = Orientation.Horizontal };
        strokeRow.Children.Add(_minStroke);
        strokeRow.Children.Add(_minStrokeLabel);
        _minStroke.ValueChanged += (_, _) => _minStrokeLabel.Text = $"  {(int)_minStroke.Value} {L.Tr("точек")}";
        _unrecognized.Items.Add(new ComboBoxItem { Content = L.Tr("отдать программе"), Tag = "passthrough" });
        _unrecognized.Items.Add(new ComboBoxItem { Content = L.Tr("проглотить"), Tag = "swallow" });
        panel.Children.Add(Theme.Card(L.Tr("Мышь"),
            Theme.Row(L.Tr("Кнопка-модификатор"), _trigger),
            Theme.Row(L.Tr("Короткое движение — щелчок"), strokeRow),
            Theme.Row(L.Tr("Если жест не распознан"), _unrecognized),
            Theme.Note(L.Tr("«Отдать программе» значит, что после неудачного росчерка откроется ")
                     + L.Tr("обычное контекстное меню. Так понятнее: видно, что жест не вышел."))));

        panel.Children.Add(Theme.Card(L.Tr("Программы"),
            _fullscreen,
            Theme.Themed(new TextBlock { Text = L.Tr("Не мешать в программах:"), Margin = new Thickness(0, 6, 0, 2) }, "RcText"),
            _excludedEditor.Panel,
            Theme.Note(L.Tr("Наведите мишень на окно программы, где жесты мешают. ")
                     + L.Tr("Строки можно снимать крестиком."))));

        var colorRow = new StackPanel { Orientation = Orientation.Horizontal };
        colorRow.Children.Add(_trailColor);
        colorRow.Children.Add(_trailSample);
        _trailColor.TextChanged += (_, _) => RefreshSample();
        panel.Children.Add(Theme.Card(L.Tr("След"),
            _trailEnabled,
            Theme.Row(L.Tr("Цвет"), colorRow),
            Theme.Row(L.Tr("Толщина"), _trailWidth),
            Theme.Row(L.Tr("Непрозрачность, %"), _trailOpacity),
            Theme.Row(L.Tr("Гаснет за, мс"), _trailFade)));

        panel.Children.Add(Theme.Card(L.Tr("Запуск и обновления"),
            _autostart,
            _checkUpdates,
            Theme.Row(L.Tr("Где лежат выпуски"), _updateRepo),
            Theme.Note(L.Tr("Раз в сутки программа спрашивает страницу выпусков, не вышла ли ")
                     + L.Tr("версия новее. Сама она не обновляется: перехват мыши — не то место, ")
                     + L.Tr("где уместна тихая подмена."))));

        _theme.Items.Add(new ComboBoxItem { Content = L.Tr("как в системе"), Tag = "system" });
        _theme.Items.Add(new ComboBoxItem { Content = L.Tr("светлая"), Tag = "light" });
        _theme.Items.Add(new ComboBoxItem { Content = L.Tr("тёмная"), Tag = "dark" });
        _language.Items.Add(new ComboBoxItem { Content = L.Tr("как в системе"), Tag = "auto" });
        _language.Items.Add(new ComboBoxItem { Content = "English", Tag = "en" });
        _language.Items.Add(new ComboBoxItem { Content = "Русский", Tag = "ru" });
        panel.Children.Add(Theme.Card(L.Tr("Оформление"),
            Theme.Row(L.Tr("Тема"), _theme),
            Theme.Row(L.Tr("Язык"), _language),
            Theme.Note(L.Tr("Язык интерфейса сменится при следующем запуске."))));

        var openFolder = new Button { Content = L.Tr("Открыть папку настроек"), Padding = new Thickness(10, 3, 10, 3) };
        openFolder.Click += (_, _) =>
        {
            _store.PrepareDirectories();
            Process.Start(new ProcessStartInfo(_store.Root) { UseShellExecute = true });
        };
        var pathRow = new StackPanel { Orientation = Orientation.Horizontal };
        pathRow.Children.Add(openFolder);
        panel.Children.Add(Theme.Card(L.Tr("Файлы"),
            pathRow,
            Theme.Note(_store.Root)));

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 0, 0, 4),
        };
        var apply = new Button { Content = L.Tr("Применить"), Padding = new Thickness(16, 4, 16, 4), Margin = new Thickness(0, 0, 8, 0), IsDefault = true };
        var close = new Button { Content = L.Tr("Закрыть"), Padding = new Thickness(16, 4, 16, 4) };
        Theme.Primary(apply);
        apply.Click += (_, _) => Apply();
        close.Click += (_, _) => Close();
        buttons.Children.Add(apply);
        buttons.Children.Add(close);
        panel.Children.Add(buttons);

        var scroll = new ScrollViewer
        {
            Content = panel,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
        scroll.SetResourceReference(BackgroundProperty, "RcWindow");
        return scroll;
    }

    private void Fill()
    {
        _trigger.SelectedIndex = string.Equals(_settings.TriggerButton, "BTN_MIDDLE",
            StringComparison.OrdinalIgnoreCase) ? 1 : 0;
        _minStroke.Value = _settings.MinStrokePx;
        _minStrokeLabel.Text = $"  {(int)_settings.MinStrokePx} {L.Tr("точек")}";
        _unrecognized.SelectedIndex = string.Equals(_settings.Unrecognized, "swallow",
            StringComparison.OrdinalIgnoreCase) ? 1 : 0;
        _fullscreen.IsChecked = _settings.PauseInFullscreen;
        _excludedEditor.Load(_settings.ExcludedApps);

        _trailEnabled.IsChecked = _settings.Overlay.Enabled;
        _trailColor.Text = _settings.Overlay.Color;
        _trailWidth.Value = _settings.Overlay.Width;
        _trailOpacity.Value = _settings.Overlay.Opacity * 100;
        _trailFade.Value = _settings.Overlay.FadeMs;
        RefreshSample();

        _autostart.IsChecked = TrayApp.LaunchesAtLogin();
        _checkUpdates.IsChecked = _settings.CheckUpdates;
        _updateRepo.Text = _settings.UpdateRepo;
        _theme.SelectedIndex = _settings.Theme switch { "light" => 1, "dark" => 2, _ => 0 };
        _language.SelectedIndex = _settings.Language switch { "en" => 1, "ru" => 2, _ => 0 };
    }

    private void RefreshSample() =>
        _trailSample.Fill = new SolidColorBrush(TrailWindow.ParseColor(_trailColor.Text));

    private void Apply()
    {
        _settings.TriggerButton = (string)((ComboBoxItem)_trigger.SelectedItem).Tag;
        _settings.MinStrokePx = Math.Round(_minStroke.Value);
        _settings.Unrecognized = (string)((ComboBoxItem)_unrecognized.SelectedItem).Tag;
        _settings.PauseInFullscreen = _fullscreen.IsChecked == true;

        _settings.Overlay.Enabled = _trailEnabled.IsChecked == true;
        _settings.Overlay.Color = _trailColor.Text.Trim();
        _settings.Overlay.Width = (int)Math.Round(_trailWidth.Value);
        _settings.Overlay.Opacity = Math.Round(_trailOpacity.Value / 100, 2);
        _settings.Overlay.FadeMs = (int)Math.Round(_trailFade.Value);

        _settings.CheckUpdates = _checkUpdates.IsChecked == true;
        _settings.UpdateRepo = _updateRepo.Text.Trim();
        _settings.Theme = (string)((ComboBoxItem)_theme.SelectedItem).Tag;
        _settings.Language = (string)((ComboBoxItem)_language.SelectedItem).Tag;

        try
        {
            _store.SaveSettings(_settings);
            TrayApp.SetLaunchAtLogin(_autostart.IsChecked == true);
        }
        catch (Exception exception)
        {
            MessageBox.Show(L.Tr("Не удалось сохранить настройки:\n\n") + exception.Message,
                            "Glyphstroke", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }
        _changed();
    }
}
