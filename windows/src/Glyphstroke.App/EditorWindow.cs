using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using Glyphstroke.Core;
using MenuItem = Glyphstroke.Core.MenuItem;
using Point = Glyphstroke.Core.Point;

namespace Glyphstroke.App;

/// <summary>Редактор жестов: слева список, справа подробности.</summary>
/// <remarks>
/// Правки сохраняются сами, через полсекунды после последнего нажатия клавиши.
/// Кнопки «Сохранить» здесь нет намеренно: жест — это не документ, человек
/// приходит поменять одну строчку, и забытая кнопка означала бы потерянную
/// правку и полчаса разбирательств, почему мышь делает старое.
///
/// Окно собрано кодом, без разметки XAML. Причина скучная и важная: так у
/// проекта одна точка сборки и нет невидимых порождаемых файлов — когда
/// ошибку ищут по пересланному сообщению компилятора, это экономит часы.
/// </remarks>
public sealed class EditorWindow : Window
{
    private readonly Store _store;
    private readonly Action _changed;

    private readonly ComboBox _profiles = new();
    private bool _switchingProfile;
    private readonly ListBox _list = new() { Width = 260 };
    private readonly TextBox _name = new();
    private readonly TextBox _description = new();
    private readonly CheckBox _enabled = new() { Content = L.Tr("Включён") };
    private readonly TextBox _directions = new();
    private AppListEditor _appsEditor = null!;
    private readonly Slider _tolerance = new() { Minimum = 0, Maximum = 45, TickFrequency = 1, IsSnapToTickEnabled = true };
    private readonly TextBlock _toleranceLabel = new();
    private readonly StackPanel _actions = new();
    private readonly StackPanel _menu = new();
    private readonly Canvas _canvas = new() { Height = 170 };
    private readonly TextBlock _canvasHint = new() { Text = L.Tr("Нарисуйте здесь фигуру жеста"), Margin = new Thickness(8), IsHitTestVisible = false };
    private readonly TextBlock _templatesLabel = new();
    private readonly WrapPanel _samples = new() { Margin = new Thickness(0, 8, 0, 0) };
    private readonly TextBlock _warning = new() { Foreground = Brushes.DarkOrange, TextWrapping = TextWrapping.Wrap };

    private readonly DispatcherTimer _saveTimer = new() { Interval = TimeSpan.FromMilliseconds(600) };
    private List<Gesture> _gestures = new();
    private Gesture? _current;
    private bool _filling;

    private readonly List<Point> _drawing = new();
    private Polyline? _drawnLine;

    public EditorWindow(Store store, Action changed)
    {
        _store = store;
        _changed = changed;

        Title = L.Tr("Glyphstroke — жесты");
        Width = 900;
        Height = 640;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _saveTimer.Tick += (_, _) => { _saveTimer.Stop(); SaveCurrent(); };
        this.SetResourceReference(BackgroundProperty, "RcWindow");
        _canvas.SetResourceReference(Panel.BackgroundProperty, "RcField");
        _canvasHint.SetResourceReference(TextBlock.ForegroundProperty, "RcMuted");
        SourceInitialized += (_, _) => Theme.ApplyWindowChrome(this);
        _appsEditor = new AppListEditor(ScheduleSave, L.Tr("Пусто — жест работает во всех программах."));
        Content = BuildLayout();
        HookChanges();
    }

    private UIElement BuildLayout()
    {
        var grid = new Grid { Margin = new Thickness(12) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        // --- слева: список и кнопки, единой карточкой ---
        var left = new DockPanel();
        var buttons = new StackPanel { Orientation = Orientation.Horizontal };
        var add = new Button { Content = L.Tr("Добавить"), Margin = new Thickness(0, 8, 6, 0), Padding = new Thickness(8, 2, 8, 2) };
        var copy = new Button { Content = L.Tr("Дублировать"), Margin = new Thickness(0, 8, 6, 0), Padding = new Thickness(8, 2, 8, 2) };
        var remove = new Button { Content = L.Tr("Удалить"), Margin = new Thickness(0, 8, 0, 0), Padding = new Thickness(8, 2, 8, 2) };
        add.Click += (_, _) => AddGesture();
        copy.Click += (_, _) => DuplicateGesture();
        remove.Click += (_, _) => RemoveGesture();
        buttons.Children.Add(add);
        buttons.Children.Add(copy);
        buttons.Children.Add(remove);
        DockPanel.SetDock(buttons, Dock.Bottom);
        left.Children.Add(buttons);
        var profileRow = BuildProfileRow();
        DockPanel.SetDock(profileRow, Dock.Top);
        left.Children.Add(profileRow);
        _list.BorderThickness = new Thickness(0);
        _list.SelectionChanged += (_, _) => FillFromSelection();
        left.Children.Add(_list);
        var leftCard = new Border
        {
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(12),
            Margin = new Thickness(0, 0, 12, 0),
            Child = left,
        };
        leftCard.SetResourceReference(Border.BackgroundProperty, "RcCard");
        leftCard.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");
        Grid.SetColumn(leftCard, 0);
        grid.Children.Add(leftCard);

        // --- справа: подробности, разбитые на карточки ---
        var directionsNote = Theme.Themed(new TextBlock
        {
            Text = L.Tr("Буквы направлений через дефис: R вправо, L влево, U вверх, D вниз, ")
                 + L.Tr("DR вниз-вправо и так далее. Несколько вариантов — через запятую."),
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 4, 0, 0),
        }, "RcMuted");
        var gestureCard = Theme.Card(L.Tr("Жест"),
            Row(L.Tr("Название"), _name),
            Row(L.Tr("Пояснение"), _description),
            _enabled,
            Row(L.Tr("Направления"), _directions),
            directionsNote,
            _warning);

        var canvasHost = new Grid();
        canvasHost.Children.Add(_canvas);
        canvasHost.Children.Add(_canvasHint);
        var canvasButtons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
        var addTemplate = new Button { Content = L.Tr("Добавить образец"), Padding = new Thickness(8, 2, 8, 2), Margin = new Thickness(0, 0, 6, 0) };
        var clearTemplates = new Button { Content = L.Tr("Убрать все образцы"), Padding = new Thickness(8, 2, 8, 2) };
        addTemplate.Click += (_, _) => AddTemplate();
        clearTemplates.Click += (_, _) => ClearTemplates();
        canvasButtons.Children.Add(addTemplate);
        canvasButtons.Children.Add(clearTemplates);
        canvasButtons.Children.Add(_templatesLabel);
        _canvas.MouseDown += CanvasDown;
        _canvas.MouseMove += CanvasMove;
        _canvas.MouseUp += CanvasUp;
        var samplesCard = Theme.Card(L.Tr("Образцы росчерка"), canvasHost, canvasButtons, _samples);

        var addAction = new Button { Content = L.Tr("Добавить действие"), Padding = new Thickness(8, 2, 8, 2), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 0) };
        addAction.Click += (_, _) =>
        {
            _current?.Actions.Add(new GestureAction("standard", "copy"));
            FillActions();
            ScheduleSave();
        };
        var actionsCard = Theme.Card(L.Tr("Действия"), _actions, addAction);

        var addMenuItem = new Button { Content = L.Tr("Добавить пункт"), Padding = new Thickness(8, 2, 8, 2), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 0) };
        addMenuItem.Click += (_, _) =>
        {
            _current?.Menu.Add(new MenuItem { Name = L.Tr("Пункт") });
            FillMenu();
            ScheduleSave();
        };
        var menuNote = Theme.Themed(new TextBlock
        {
            Text = L.Tr("Если есть пункты, жест открывает меню у курсора: выбери пункт — ")
                 + L.Tr("выполнятся его действия. Без пунктов жест просто делает свои действия."),
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 6),
        }, "RcMuted");
        var menuCard = Theme.Card(L.Tr("Меню"), menuNote, _menu, addMenuItem);

        var toleranceRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 10, 0, 0) };
        var toleranceTip = L.Tr("Насколько сильно рисунок может быть повёрнут и всё равно распознаться. 0° — строго как образец; больше — терпимее к наклону руки.");
        toleranceRow.Children.Add(new TextBlock { Text = L.Tr("Допуск поворота"), Width = 150, VerticalAlignment = VerticalAlignment.Center, ToolTip = toleranceTip });
        _tolerance.Width = 200; _tolerance.ToolTip = toleranceTip;
        toleranceRow.Children.Add(_tolerance);
        toleranceRow.Children.Add(_toleranceLabel);
        var whereCard = Theme.Card(L.Tr("Где работает"),
            _appsEditor.Panel,
            toleranceRow);

        // Вкладки Росчерк / Действия / Меню — как в версии для Linux.
        var shapePage = new StackPanel { Margin = new Thickness(0, 0, 12, 0) };
        shapePage.Children.Add(gestureCard);
        shapePage.Children.Add(samplesCard);
        shapePage.Children.Add(whereCard);

        var actionsPage = new StackPanel { Margin = new Thickness(0, 0, 12, 0) };
        actionsPage.Children.Add(actionsCard);

        var menuPage = new StackPanel { Margin = new Thickness(0, 0, 12, 0) };
        menuPage.Children.Add(menuCard);

        var tabs = BuildTabs(
            (L.Tr("Росчерк"), shapePage),
            (L.Tr("Действия"), actionsPage),
            (L.Tr("Меню"), menuPage));
        Grid.SetColumn(tabs, 1);
        grid.Children.Add(tabs);
        return grid;
    }

    private static UIElement Row(string title, FrameworkElement field)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
        row.Children.Add(new TextBlock { Text = title, Width = 150, VerticalAlignment = VerticalAlignment.Center });
        field.Width = 420;
        field.HorizontalAlignment = HorizontalAlignment.Left;
        row.Children.Add(field);
        return row;
    }

    private void HookChanges()
    {
        _name.TextChanged += (_, _) => ScheduleSave();
        _description.TextChanged += (_, _) => ScheduleSave();
        _directions.TextChanged += (_, _) => { UpdateWarning(); ScheduleSave(); };
        _enabled.Checked += (_, _) => ScheduleSave();
        _enabled.Unchecked += (_, _) => ScheduleSave();
        _tolerance.ValueChanged += (_, _) =>
        {
            _toleranceLabel.Text = $"  {(int)_tolerance.Value}°";
            ScheduleSave();
        };
    }

    // --- список ---

    public void ReloadFromDisk()
    {
        string? selected = _current?.FilePath;
        _gestures = _store.LoadGestures();
        FillList();
        var restored = _gestures.FirstOrDefault(gesture => gesture.FilePath == selected) ?? _gestures.FirstOrDefault();
        _list.SelectedIndex = restored is null ? -1 : _gestures.IndexOf(restored);
    }

    private void FillList()
    {
        _filling = true;
        _list.Items.Clear();
        foreach (var gesture in _gestures)
        {
            string mark = gesture.Enabled ? "" : L.Tr("  (выкл)");
            string shape = gesture.Directions.Count > 0
                ? string.Join(", ", gesture.Directions)
                : gesture.Templates.Count > 0 ? $"{L.Tr("образцов:")} {gesture.Templates.Count}"
                : gesture.Event.Length > 0 ? gesture.Event : L.Tr("фигура не задана");
            _list.Items.Add($"{gesture.Name}{mark}\n{shape}");
        }
        _filling = false;
    }

    private void FillFromSelection()
    {
        if (_filling)
        {
            return;
        }
        CommitPending();
        int index = _list.SelectedIndex;
        _current = index >= 0 && index < _gestures.Count ? _gestures[index] : null;
        if (_current is null)
        {
            return;
        }

        _filling = true;
        _name.Text = _current.Name;
        _description.Text = _current.Description;
        _enabled.IsChecked = _current.Enabled;
        _directions.Text = string.Join(", ", _current.Directions);
        _tolerance.Value = _current.RotationTolerance;
        _toleranceLabel.Text = $"  {(int)_current.RotationTolerance}°";
        _filling = false;

        _appsEditor.Load(_current.Apps);
        FillActions();
        FillMenu();
        UpdateTemplatesLabel();
        UpdateWarning();
        ClearDrawing();
    }

    private void FillMenu()
    {
        _menu.Children.Clear();
        if (_current is null)
        {
            return;
        }
        foreach (var item in _current.Menu.ToList())
        {
            var nameBox = new TextBox { Text = item.Name };
            nameBox.TextChanged += (_, _) => { item.Name = nameBox.Text; ScheduleSave(); };

            var actionsPanel = new StackPanel { Margin = new Thickness(0, 4, 0, 0) };
            void Refill() => FillActionRows(item.Actions, actionsPanel, Refill);
            Refill();

            var addAction = new Button { Content = L.Tr("Добавить действие"), Padding = new Thickness(8, 2, 8, 2), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 4, 0, 0) };
            addAction.Click += (_, _) => { item.Actions.Add(new GestureAction("keys", string.Empty)); Refill(); ScheduleSave(); };

            var removeItem = new Button { Content = L.Tr("Убрать пункт"), Padding = new Thickness(8, 2, 8, 2), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 0) };
            removeItem.Click += (_, _) => { _current!.Menu.Remove(item); FillMenu(); ScheduleSave(); };

            var box = new StackPanel();
            box.Children.Add(Theme.Row(L.Tr("Название пункта"), nameBox));
            box.Children.Add(actionsPanel);
            box.Children.Add(addAction);
            box.Children.Add(removeItem);

            var border = new Border
            {
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(12),
                Margin = new Thickness(0, 6, 0, 0),
                Child = box,
            };
            border.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");
            _menu.Children.Add(border);
        }
    }

    private void FillActions()
    {
        if (_current is null)
        {
            _actions.Children.Clear();
            return;
        }
        FillActionRows(_current.Actions, _actions, FillActions);
    }

    /// <summary>Построить строки редактора действий для произвольного списка.</summary>
    private void FillActionRows(List<GestureAction> actions, Panel container, Action refill)
    {
        container.Children.Clear();
        foreach (var action in actions.ToList())
        {
            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };

            var type = new ComboBox { Width = 170 };
            foreach (var (typeId, title) in ActionTypes)
            {
                type.Items.Add(new ComboBoxItem { Content = title, Tag = typeId });
            }
            type.SelectedIndex = Math.Max(0, ActionTypes.FindIndex(item => item.Value == action.Type));

            var standard = new ComboBox { Width = 260, Visibility = Visibility.Collapsed };
            foreach (var entry in StandardActions.All)
            {
                standard.Items.Add(new ComboBoxItem { Content = StandardActions.Describe(entry.Id), Tag = entry.Id });
            }
            standard.SelectedIndex = Math.Max(0,
                StandardActions.All.ToList().FindIndex(entry => entry.Id == action.Value));

            var value = new TextBox { Width = 260, Text = action.Value };
            var remove = new Button { Content = "✕", Margin = new Thickness(6, 0, 0, 0), Padding = new Thickness(6, 0, 6, 0) };

            void ApplyVisibility()
            {
                bool isStandard = (string)((ComboBoxItem)type.SelectedItem).Tag == "standard";
                standard.Visibility = isStandard ? Visibility.Visible : Visibility.Collapsed;
                value.Visibility = isStandard ? Visibility.Collapsed : Visibility.Visible;
            }

            type.SelectionChanged += (_, _) =>
            {
                action.Type = (string)((ComboBoxItem)type.SelectedItem).Tag;
                if (action.Type == "standard" && StandardActions.Find(action.Value) is null)
                {
                    action.Value = "copy";
                    standard.SelectedIndex = 0;
                }
                ApplyVisibility();
                ScheduleSave();
            };
            standard.SelectionChanged += (_, _) =>
            {
                if (standard.SelectedItem is ComboBoxItem item)
                {
                    action.Value = (string)item.Tag;
                    ScheduleSave();
                }
            };
            value.TextChanged += (_, _) =>
            {
                action.Value = value.Text;
                ScheduleSave();
            };
            remove.Click += (_, _) =>
            {
                actions.Remove(action);
                refill();
                ScheduleSave();
            };

            ApplyVisibility();
            row.Children.Add(type);
            row.Children.Add(standard);
            row.Children.Add(value);
            row.Children.Add(remove);
            container.Children.Add(row);
        }
    }

    private static readonly List<(string Value, string Title)> ActionTypes = new()
    {
        ("standard", L.Tr("Стандартное действие")),
        ("keys", L.Tr("Клавиши")),
        ("text", L.Tr("Ввести текст")),
        ("command", L.Tr("Команда")),
        ("app", L.Tr("Запуск программы")),
        ("window", L.Tr("Окно")),
        ("button", L.Tr("Кнопка мыши")),
        ("scroll", L.Tr("Прокрутка")),
        ("delay", L.Tr("Пауза, мс")),
        ("none", L.Tr("Ничего")),
    };

    // --- рисование образцов ---

    private void CanvasDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left)
        {
            return;
        }
        _drawing.Clear();
        _drawnLine = new Polyline
        {
            Stroke = Brushes.SteelBlue,
            StrokeThickness = 3,
            StrokeLineJoin = PenLineJoin.Round,
        };
        _canvas.Children.Clear();
        _canvas.Children.Add(_drawnLine);
        _canvasHint.Visibility = Visibility.Collapsed;
        _canvas.CaptureMouse();
        AddDrawingPoint(e.GetPosition(_canvas));
    }

    private void CanvasMove(object sender, MouseEventArgs e)
    {
        if (_drawnLine is null || e.LeftButton != MouseButtonState.Pressed)
        {
            return;
        }
        AddDrawingPoint(e.GetPosition(_canvas));
    }

    private void CanvasUp(object sender, MouseButtonEventArgs e)
    {
        _canvas.ReleaseMouseCapture();
        if (_drawing.Count > 1)
        {
            _templatesLabel.Text = $"  {L.Tr("код нарисованного:")} {DirectionCode.Of(_drawing)}";
        }
    }

    private void AddDrawingPoint(System.Windows.Point point)
    {
        _drawing.Add(new Point(point.X, point.Y));
        _drawnLine?.Points.Add(point);
    }

    private void AddTemplate()
    {
        if (_current is null || _drawing.Count < 2)
        {
            return;
        }
        _current.Templates.Add(_drawing.ToList());
        ClearDrawing();
        UpdateTemplatesLabel();
        ScheduleSave();
    }

    private void ClearTemplates()
    {
        if (_current is null)
        {
            return;
        }
        _current.Templates.Clear();
        UpdateTemplatesLabel();
        ScheduleSave();
    }

    private void ClearDrawing()
    {
        _drawing.Clear();
        _drawnLine = null;
        _canvas.Children.Clear();
        _canvasHint.Visibility = Visibility.Visible;
    }

    private void UpdateTemplatesLabel()
    {
        _templatesLabel.Text = _current is null ? string.Empty : $"  {L.Tr("образцов:")} {_current.Templates.Count}";
        RefreshSamples();
    }

    /// <summary>Полоса миниатюр сохранённых образцов — как в версиях для Linux и macOS.</summary>
    private void RefreshSamples()
    {
        _samples.Children.Clear();
        if (_current is null)
        {
            return;
        }
        for (int i = 0; i < _current.Templates.Count; i++)
        {
            _samples.Children.Add(SampleThumbnail(_current.Templates[i], i));
        }
    }

    private UIElement SampleThumbnail(List<Point> points, int index)
    {
        var canvas = new Canvas { Width = 60, Height = 60 };
        var fitted = FitPoints(points, 60, 60, 6);
        if (fitted.Count > 1)
        {
            var line = new Polyline { StrokeThickness = 2, StrokeLineJoin = PenLineJoin.Round };
            line.SetResourceReference(Shape.StrokeProperty, "RcText");
            foreach (var point in fitted)
            {
                line.Points.Add(new System.Windows.Point(point.X, point.Y));
            }
            canvas.Children.Add(line);
        }

        var remove = new Button
        {
            Content = "\u00d7",
            Width = 18,
            Height = 18,
            Padding = new Thickness(0),
            FontSize = 12,
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Top,
            Margin = new Thickness(0, 2, 2, 0),
        };
        remove.Click += (_, _) =>
        {
            if (_current is not null && index < _current.Templates.Count)
            {
                _current.Templates.RemoveAt(index);
                UpdateTemplatesLabel();
                ScheduleSave();
            }
        };

        var host = new Grid();
        host.Children.Add(canvas);
        host.Children.Add(remove);

        var border = new Border
        {
            Width = 64,
            Height = 64,
            CornerRadius = new CornerRadius(6),
            BorderThickness = new Thickness(1),
            Margin = new Thickness(0, 0, 6, 6),
            Child = host,
        };
        border.SetResourceReference(Border.BackgroundProperty, "RcField");
        border.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");
        return border;
    }

    /// <summary>Вписать росчерк в квадрат, сохранив пропорции.</summary>
    private static List<System.Windows.Point> FitPoints(List<Point> points, double width, double height, double pad)
    {
        var result = new List<System.Windows.Point>();
        if (points.Count == 0)
        {
            return result;
        }
        double minX = points.Min(p => p.X), maxX = points.Max(p => p.X);
        double minY = points.Min(p => p.Y), maxY = points.Max(p => p.Y);
        double boxW = Math.Max(maxX - minX, 1), boxH = Math.Max(maxY - minY, 1);
        double scale = Math.Min((width - pad * 2) / boxW, (height - pad * 2) / boxH);
        double offX = (width - boxW * scale) / 2, offY = (height - boxH * scale) / 2;
        foreach (var point in points)
        {
            result.Add(new System.Windows.Point((point.X - minX) * scale + offX, (point.Y - minY) * scale + offY));
        }
        return result;
    }

    // --- правки ---

    private void ScheduleSave()
    {
        if (_filling || _current is null)
        {
            return;
        }
        _saveTimer.Stop();
        _saveTimer.Start();
    }

    /// <summary>Переписать значения полей в объект жеста (без записи на диск).</summary>
    private void WriteFieldsTo(Gesture gesture)
    {
        gesture.Name = _name.Text.Trim().Length == 0 ? L.Tr("Без названия") : _name.Text.Trim();
        gesture.Description = _description.Text;
        gesture.Enabled = _enabled.IsChecked == true;
        gesture.Directions = _directions.Text
            .Split(new[] { ',', ' ' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(part => part.Trim().ToUpperInvariant())
            .Where(part => part.Length > 0)
            .ToList();
        gesture.RotationTolerance = Math.Round(_tolerance.Value);
    }

    /// <summary>
    /// Сохранить отложенные правки текущего жеста немедленно, ничего не перестраивая.
    /// Нужен перед сменой жеста (кнопка «Добавить»/«Дублировать» или выбор в
    /// списке): раньше введённое между нажатием и срабатыванием 600-мс таймера
    /// пропадало.
    /// </summary>
    private void CommitPending()
    {
        if (!_saveTimer.IsEnabled || _current is null)
        {
            return;
        }
        _saveTimer.Stop();
        WriteFieldsTo(_current);
        try
        {
            _store.Save(_current);
        }
        catch (Exception)
        {
            // Лучшее усилие: не показываем окно посреди смены жеста.
        }
    }

    private void SaveCurrent()
    {
        if (_current is null)
        {
            return;
        }
        WriteFieldsTo(_current);

        try
        {
            _store.Save(_current);
        }
        catch (Exception exception)
        {
            MessageBox.Show(L.Tr("Не удалось сохранить жест:\n\n") + exception.Message,
                            "Glyphstroke", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        int index = _list.SelectedIndex;
        FillList();
        _list.SelectedIndex = index;
        UpdateWarning();
        _changed();
    }

    private void UpdateWarning()
    {
        if (_current is null)
        {
            _warning.Text = string.Empty;
            return;
        }
        var mine = _directions.Text
            .Split(new[] { ',', ' ' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(part => part.Trim().ToUpperInvariant())
            .ToHashSet();
        var clashing = _gestures
            .Where(gesture => gesture.Enabled && gesture.FilePath != _current.FilePath
                              && gesture.Directions.Any(code => mine.Contains(code)))
            .Select(gesture => gesture.Name)
            .ToList();
        _warning.Text = clashing.Count == 0
            ? string.Empty
            : $"{L.Tr("Та же фигура у:")} {string.Join(", ", clashing)}. "
              + L.Tr("Пока фигуры совпадают, не сработает ни один из жестов.");
    }

    // --- список жестов ---

    /// <summary>Свои вкладки: ряд заголовков с оранжевым подчёркиванием активной.</summary>
    private UIElement BuildTabs(params (string Title, UIElement Content)[] pages)
    {
        var host = new DockPanel();
        var headers = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
        DockPanel.SetDock(headers, Dock.Top);
        var body = new Grid();

        var underlines = new List<Border>();
        var texts = new List<TextBlock>();
        var scrolls = new List<ScrollViewer>();

        void Select(int active)
        {
            for (int i = 0; i < scrolls.Count; i++)
            {
                scrolls[i].Visibility = i == active ? Visibility.Visible : Visibility.Collapsed;
                texts[i].FontWeight = i == active ? FontWeights.SemiBold : FontWeights.Normal;
                if (i == active)
                {
                    underlines[i].SetResourceReference(Border.BackgroundProperty, "RcSelect");
                }
                else
                {
                    underlines[i].Background = Brushes.Transparent;
                }
            }
        }

        for (int i = 0; i < pages.Length; i++)
        {
            int index = i;
            var text = Theme.Themed(new TextBlock { Text = pages[i].Title, FontSize = 14 }, "RcText");
            var underline = new Border { Height = 3, CornerRadius = new CornerRadius(2), Margin = new Thickness(0, 5, 0, 0), Background = Brushes.Transparent };
            var column = new StackPanel { Margin = new Thickness(0, 0, 20, 0) };
            column.Children.Add(text);
            column.Children.Add(underline);
            var tab = new Border { Child = column, Background = Brushes.Transparent, Cursor = Cursors.Hand };
            tab.MouseLeftButtonUp += (_, _) => Select(index);
            headers.Children.Add(tab);

            var scroll = new ScrollViewer
            {
                Content = pages[i].Content,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            };
            scroll.SetResourceReference(Control.BackgroundProperty, "RcWindow");
            body.Children.Add(scroll);

            underlines.Add(underline);
            texts.Add(text);
            scrolls.Add(scroll);
        }

        host.Children.Add(headers);
        host.Children.Add(body);
        Select(0);
        return host;
    }

    // --- наборы жестов (профили) ---

    private UIElement BuildProfileRow()
    {
        var row = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
        var add = new Button { Content = L.Tr("Новый"), Padding = new Thickness(10, 2, 10, 2), Margin = new Thickness(6, 0, 0, 0), ToolTip = L.Tr("Новый набор жестов") };
        var remove = new Button { Content = L.Tr("Удалить"), Padding = new Thickness(10, 2, 10, 2), Margin = new Thickness(6, 0, 0, 0), ToolTip = L.Tr("Удалить набор") };
        add.Click += (_, _) => AddProfile();
        remove.Click += (_, _) => RemoveCurrentProfile();
        DockPanel.SetDock(remove, Dock.Right);
        DockPanel.SetDock(add, Dock.Right);
        row.Children.Add(remove);
        row.Children.Add(add);
        _profiles.SelectionChanged += (_, _) => OnProfileSelected();
        row.Children.Add(_profiles);
        PopulateProfiles();
        return row;
    }

    private void PopulateProfiles()
    {
        _switchingProfile = true;
        _profiles.Items.Clear();
        _profiles.Items.Add(new ComboBoxItem { Content = L.Tr("Основной"), Tag = string.Empty });
        foreach (var name in _store.AvailableProfiles())
        {
            _profiles.Items.Add(new ComboBoxItem { Content = name, Tag = name });
        }
        int index = 0;
        for (int i = 0; i < _profiles.Items.Count; i++)
        {
            if ((string)((ComboBoxItem)_profiles.Items[i]).Tag == _store.ActiveProfile)
            {
                index = i;
                break;
            }
        }
        _profiles.SelectedIndex = index;
        _switchingProfile = false;
    }

    private void OnProfileSelected()
    {
        if (_switchingProfile || _profiles.SelectedItem is not ComboBoxItem item)
        {
            return;
        }
        SwitchProfile((string)item.Tag);
    }

    private void SwitchProfile(string name)
    {
        CommitPending();
        _store.ActiveProfile = name;
        var settings = _store.LoadSettings();
        settings.ActiveProfile = name;
        try
        {
            _store.SaveSettings(settings);
        }
        catch (Exception)
        {
            // Не удалось записать выбор набора — жесты всё равно перечитаем.
        }
        _store.PrepareDirectories();
        ReloadFromDisk();
        _changed();
    }

    private void AddProfile()
    {
        string? name = InputDialog.Ask(this, L.Tr("Новый набор жестов"), L.Tr("Название набора"));
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }
        string created = _store.CreateProfile(name, _store.ActiveProfile);
        if (created.Length == 0)
        {
            return;
        }
        SwitchProfile(created);
        PopulateProfiles();
    }

    private void RemoveCurrentProfile()
    {
        if (string.IsNullOrEmpty(_store.ActiveProfile))
        {
            return;
        }
        string name = _store.ActiveProfile;
        if (MessageBox.Show($"{L.Tr("Удалить набор")} «{name}»?", "Glyphstroke",
                            MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
        {
            return;
        }
        _store.RemoveProfile(name);
        SwitchProfile(string.Empty);
        PopulateProfiles();
    }

    private void AddGesture()
    {
        CommitPending();
        var gesture = new Gesture { Name = UniqueName(L.Tr("Новый жест")) };
        _store.Save(gesture);
        ReloadFromDisk();
        _list.SelectedIndex = _gestures.FindIndex(item => item.Name == gesture.Name);
        _changed();
    }

    private void DuplicateGesture()
    {
        if (_current is null)
        {
            return;
        }
        CommitPending();
        var copy = Store.ReadGesture(_current.FilePath!);
        if (copy is null)
        {
            return;
        }
        copy.Name = UniqueName(_current.Name);
        copy.FilePath = null;
        _store.Save(copy);
        ReloadFromDisk();
        _list.SelectedIndex = _gestures.FindIndex(item => item.Name == copy.Name);
        _changed();
    }

    private void RemoveGesture()
    {
        if (_current is null)
        {
            return;
        }
        if (MessageBox.Show($"{L.Tr("Удалить жест")} «{_current.Name}»?", "Glyphstroke",
                            MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
        {
            return;
        }
        _store.Delete(_current);
        _current = null;
        ReloadFromDisk();
        _changed();
    }

    private string UniqueName(string baseName)
    {
        string candidate = baseName;
        int counter = 2;
        while (_gestures.Any(gesture => gesture.Name == candidate))
        {
            candidate = $"{baseName} {counter++}";
        }
        return candidate;
    }
}
