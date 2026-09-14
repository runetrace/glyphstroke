using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using System.Windows.Interop;
using System.Runtime.InteropServices;
using System.Windows.Media;
using Microsoft.Win32;

namespace Glyphstroke.App;

/// <summary>
/// Единый вид окон — как в базовой версии для Linux: тёмная или светлая тема
/// по настройке системы, зелёный акцент у главных кнопок и оранжевый у
/// выделения, тумблеров и слайдеров, скруглённые карточки-разделы.
/// </summary>
/// <remarks>
/// WPF по умолчанию рисует контролы светлой «аэро»-темой, поэтому одной сменой
/// фона тёмный вид не получить: нужны шаблоны для полей, кнопок, списков,
/// слайдеров и переключателей. Шаблоны заданы разметкой (<see cref="ThemeXaml"/>)
/// и ставятся в ресурсы приложения один раз при запуске. Если разметку почему-то
/// не удалось разобрать, программа не падает: <see cref="Install"/> ловит ошибку
/// и оставляет хотя бы тёмный фон и цвет текста.
/// </remarks>
internal static class Theme
{
    public static bool Dark { get; private set; }

    public static Brush WindowFill { get; private set; } = Brushes.White;
    public static Brush CardFill { get; private set; } = Brushes.White;
    public static Brush CardBorder { get; private set; } = Brushes.Gray;
    public static Brush Heading { get; private set; } = Brushes.Black;
    public static Brush Muted { get; private set; } = Brushes.Gray;
    public static Brush CanvasFill { get; private set; } = Brushes.WhiteSmoke;

    /// <summary>Словарь с кистями палитры — держим ссылку, чтобы менять их вживую.</summary>
    private static ResourceDictionary? _paletteDict;

    /// <summary>
    /// Выбрать тему по системе и поставить шаблоны в ресурсы приложения.
    /// Вызывать один раз при запуске, до создания окон.
    /// </summary>
    public static void Install(Application app, string theme)
    {
        // Палитра — в отдельном словаре: шаблоны контролов ссылаются на её кисти
        // через DynamicResource, поэтому подмена кистей здесь перекрашивает окна
        // на ходу (см. SetTheme).
        _paletteDict = new ResourceDictionary();
        app.Resources.MergedDictionaries.Add(_paletteDict);
        ApplyPalette(theme);

        try
        {
            var styles = (ResourceDictionary)XamlReader.Parse(ThemeXaml);
            app.Resources.MergedDictionaries.Add(styles);
        }
        catch (Exception)
        {
            // Разметку не разобрали — оставляем минимум, чтобы окна были читаемы.
            InstallFallback(app, Dark ? DarkPalette() : LightPalette());
        }
    }

    /// <summary>Сменить тему вживую: перекрасить кисти палитры и рамки открытых окон.</summary>
    public static void SetTheme(string theme)
    {
        if (_paletteDict is null)
        {
            return;
        }
        ApplyPalette(theme);
        if (Application.Current is { } app)
        {
            foreach (Window window in app.Windows)
            {
                ApplyWindowChrome(window);
            }
        }
    }

    /// <summary>Пересчитать палитру по выбору темы и обновить кисти и статические поля.</summary>
    private static void ApplyPalette(string theme)
    {
        Dark = theme switch
        {
            "dark" => true,
            "light" => false,
            _ => SystemPrefersDark(),
        };
        var p = Dark ? DarkPalette() : LightPalette();

        WindowFill = p["RcWindow"];
        CardFill = p["RcCard"];
        CardBorder = p["RcCardBorder"];
        Heading = p["RcText"];
        Muted = p["RcMuted"];
        CanvasFill = p["RcField"];

        if (_paletteDict is not null)
        {
            foreach (var pair in p)
            {
                _paletteDict[pair.Key] = pair.Value;
            }
        }
    }

    /// <summary>Пометить кнопку главной — зелёной.</summary>
    public static void Primary(Button button)
    {
        if (Application.Current?.TryFindResource("RcPrimary") is Style style)
        {
            button.Style = style;
        }
    }

    /// <summary>Тёмный/светлый цвет текста, который следует за темой вживую.</summary>
    public static TextBlock Themed(TextBlock block, string key)
    {
        block.SetResourceReference(TextBlock.ForegroundProperty, key);
        return block;
    }

    /// <summary>Заголовок раздела.</summary>
    public static TextBlock Header(string text) => Themed(new TextBlock
    {
        Text = text,
        FontWeight = FontWeights.SemiBold,
        FontSize = 14,
        Margin = new Thickness(0, 0, 0, 8),
    }, "RcText");

    /// <summary>Серое пояснение под контролом.</summary>
    public static TextBlock Note(string text) => Themed(new TextBlock
    {
        Text = text,
        FontSize = 12,
        TextWrapping = TextWrapping.Wrap,
        Margin = new Thickness(0, 4, 0, 0),
    }, "RcMuted");

    /// <summary>Строка «подпись — поле».</summary>
    public static UIElement Row(string title, UIElement field, double labelWidth = 190)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 3, 0, 3) };
        row.Children.Add(Themed(new TextBlock
        {
            Text = title,
            Width = labelWidth,
            VerticalAlignment = VerticalAlignment.Center,
        }, "RcText"));
        row.Children.Add(field);
        return row;
    }

    /// <summary>Карточка-раздел: блок с рамкой на фоне окна.</summary>
    public static Border Card(string title, params UIElement[] children)
    {
        var inner = new StackPanel();
        inner.Children.Add(Header(title));
        foreach (var child in children)
        {
            inner.Children.Add(child);
        }
        var border = new Border
        {
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(16, 14, 16, 14),
            Margin = new Thickness(0, 0, 0, 12),
            Child = inner,
        };
        border.SetResourceReference(Border.BackgroundProperty, "RcCard");
        border.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");
        return border;
    }

    /// <summary>Тёмная рамка/заголовок окна под тёмную тему (Windows 10/11).</summary>
    public static void ApplyWindowChrome(Window window)
    {
        try
        {
            var hwnd = new WindowInteropHelper(window).EnsureHandle();
            int on = Dark ? 1 : 0;
            // 20 — DWMWA_USE_IMMERSIVE_DARK_MODE; на старых сборках это 19.
            if (DwmSetWindowAttribute(hwnd, 20, ref on, sizeof(int)) != 0)
            {
                DwmSetWindowAttribute(hwnd, 19, ref on, sizeof(int));
            }
            // 33 — DWMWA_WINDOW_CORNER_PREFERENCE, 2 — DWMWCP_ROUND: скруглённые
            // углы окна. На Windows 11 это и так по умолчанию, но просим явно;
            // на Windows 10 атрибут просто игнорируется.
            int round = 2;
            DwmSetWindowAttribute(hwnd, 33, ref round, sizeof(int));
        }
        catch (Exception)
        {
            // Нет dwmapi или не та версия Windows — рамка останется обычной.
        }
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    private static bool SystemPrefersDark()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            // AppsUseLightTheme = 0 значит тёмная тема приложений.
            return key?.GetValue("AppsUseLightTheme") is int light && light == 0;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static SolidColorBrush Hex(string hex)
    {
        var value = Convert.ToUInt32(hex, 16);
        var brush = new SolidColorBrush(Color.FromRgb(
            (byte)(value >> 16), (byte)(value >> 8), (byte)value));
        brush.Freeze();
        return brush;
    }

    private static System.Collections.Generic.Dictionary<string, Brush> DarkPalette() => new()
    {
        ["RcWindow"] = Hex("242424"),
        ["RcCard"] = Hex("303030"),
        ["RcCardBorder"] = Hex("3a3a3a"),
        ["RcText"] = Hex("f2f2f2"),
        ["RcMuted"] = Hex("9aa0a6"),
        ["RcField"] = Hex("1c1c1c"),
        ["RcFieldBorder"] = Hex("4a4a4a"),
        ["RcButton"] = Hex("383838"),
        ["RcButtonHover"] = Hex("444444"),
        ["RcButtonPressed"] = Hex("2b2b2b"),
        ["RcButtonBorder"] = Hex("4a4a4a"),
        ["RcAccent"] = Hex("26a269"),
        ["RcAccentHover"] = Hex("2ec27e"),
        ["RcAccentPressed"] = Hex("1f8b5a"),
        ["RcSelect"] = Hex("e66100"),
        ["RcSelectHover"] = Hex("ff7800"),
        ["RcHover"] = Hex("3a3a3a"),
        ["RcTrackBg"] = Hex("4a4a4a"),
        ["RcToggleOff"] = Hex("5a5a5a"),
    };

    private static System.Collections.Generic.Dictionary<string, Brush> LightPalette() => new()
    {
        ["RcWindow"] = Hex("f6f5f4"),
        ["RcCard"] = Hex("ffffff"),
        ["RcCardBorder"] = Hex("d8d8d8"),
        ["RcText"] = Hex("2e2e2e"),
        ["RcMuted"] = Hex("6a6a6a"),
        ["RcField"] = Hex("ffffff"),
        ["RcFieldBorder"] = Hex("c9c9c9"),
        ["RcButton"] = Hex("ededed"),
        ["RcButtonHover"] = Hex("e3e3e3"),
        ["RcButtonPressed"] = Hex("d6d6d6"),
        ["RcButtonBorder"] = Hex("c4c4c4"),
        ["RcAccent"] = Hex("26a269"),
        ["RcAccentHover"] = Hex("2ec27e"),
        ["RcAccentPressed"] = Hex("1f8b5a"),
        ["RcSelect"] = Hex("e66100"),
        ["RcSelectHover"] = Hex("ff7800"),
        ["RcHover"] = Hex("ececec"),
        ["RcTrackBg"] = Hex("d0d0d0"),
        ["RcToggleOff"] = Hex("c4c4c4"),
    };

    private static void InstallFallback(Application app, System.Collections.Generic.Dictionary<string, Brush> p)
    {
        var text = new Style(typeof(TextBlock));
        text.Setters.Add(new Setter(TextBlock.ForegroundProperty, p["RcText"]));
        app.Resources.Add(typeof(TextBlock), text);

        var box = new Style(typeof(TextBox));
        box.Setters.Add(new Setter(Control.BackgroundProperty, p["RcField"]));
        box.Setters.Add(new Setter(Control.ForegroundProperty, p["RcText"]));
        box.Setters.Add(new Setter(Control.BorderBrushProperty, p["RcFieldBorder"]));
        app.Resources.Add(typeof(TextBox), box);
    }

    /// <summary>Шаблоны контролов. Цвета берутся из палитры по ключам Rc*.</summary>
    private const string ThemeXaml = @"
<ResourceDictionary xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'
                    xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>

  <Style TargetType='TextBox'>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
    <Setter Property='CaretBrush' Value='{DynamicResource RcText}'/>
    <Setter Property='Background' Value='{DynamicResource RcField}'/>
    <Setter Property='BorderBrush' Value='{DynamicResource RcFieldBorder}'/>
    <Setter Property='BorderThickness' Value='1'/>
    <Setter Property='Padding' Value='6,4,6,4'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='TextBox'>
          <Border CornerRadius='6' Background='{TemplateBinding Background}'
                  BorderBrush='{TemplateBinding BorderBrush}' BorderThickness='{TemplateBinding BorderThickness}'>
            <ScrollViewer x:Name='PART_ContentHost' Margin='{TemplateBinding Padding}'/>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType='Button'>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
    <Setter Property='Padding' Value='12,5,12,5'/>
    <Setter Property='SnapsToDevicePixels' Value='True'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='Button'>
          <Border x:Name='b' CornerRadius='7' Background='{DynamicResource RcButton}'
                  BorderBrush='{DynamicResource RcButtonBorder}' BorderThickness='1'>
            <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'
                              Margin='{TemplateBinding Padding}'/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property='IsMouseOver' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcButtonHover}'/>
            </Trigger>
            <Trigger Property='IsPressed' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcButtonPressed}'/>
            </Trigger>
            <Trigger Property='IsEnabled' Value='False'>
              <Setter Property='Opacity' Value='0.5'/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key='RcPrimary' TargetType='Button'>
    <Setter Property='Foreground' Value='White'/>
    <Setter Property='Padding' Value='14,5,14,5'/>
    <Setter Property='SnapsToDevicePixels' Value='True'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='Button'>
          <Border x:Name='b' CornerRadius='7' Background='{DynamicResource RcAccent}' BorderThickness='0'>
            <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'
                              Margin='{TemplateBinding Padding}'/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property='IsMouseOver' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcAccentHover}'/>
            </Trigger>
            <Trigger Property='IsPressed' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcAccentPressed}'/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType='CheckBox'>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
    <Setter Property='Margin' Value='0,3,0,3'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='CheckBox'>
          <StackPanel Orientation='Horizontal'>
            <Border x:Name='track' Width='42' Height='22' CornerRadius='11'
                    Background='{DynamicResource RcToggleOff}'>
              <Border x:Name='knob' Width='18' Height='18' CornerRadius='9'
                      HorizontalAlignment='Left' Margin='2,0,0,0' Background='White'/>
            </Border>
            <ContentPresenter Margin='10,0,0,0' VerticalAlignment='Center'/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property='IsChecked' Value='True'>
              <Setter TargetName='track' Property='Background' Value='{DynamicResource RcSelect}'/>
              <Setter TargetName='knob' Property='HorizontalAlignment' Value='Right'/>
              <Setter TargetName='knob' Property='Margin' Value='0,0,2,0'/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType='ComboBox'>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
    <Setter Property='Height' Value='30'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='ComboBox'>
          <Grid>
            <ToggleButton Focusable='False' ClickMode='Press'
                IsChecked='{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}'>
              <ToggleButton.Template>
                <ControlTemplate TargetType='ToggleButton'>
                  <Border CornerRadius='6' Background='{DynamicResource RcField}'
                          BorderBrush='{DynamicResource RcFieldBorder}' BorderThickness='1'>
                    <Grid>
                      <Grid.ColumnDefinitions>
                        <ColumnDefinition Width='*'/>
                        <ColumnDefinition Width='24'/>
                      </Grid.ColumnDefinitions>
                      <Path Grid.Column='1' HorizontalAlignment='Center' VerticalAlignment='Center'
                            Data='M0,0 L4,4 L8,0 Z' Fill='{DynamicResource RcMuted}'/>
                    </Grid>
                  </Border>
                </ControlTemplate>
              </ToggleButton.Template>
            </ToggleButton>
            <ContentPresenter IsHitTestVisible='False' TextElement.Foreground='{DynamicResource RcText}'
                Content='{TemplateBinding SelectionBoxItem}'
                ContentTemplate='{TemplateBinding SelectionBoxItemTemplate}'
                Margin='10,0,28,0' VerticalAlignment='Center'/>
            <Popup x:Name='PART_Popup' Placement='Bottom' Focusable='False'
                   IsOpen='{TemplateBinding IsDropDownOpen}' AllowsTransparency='True' PopupAnimation='Slide'>
              <Border Background='{DynamicResource RcCard}' BorderBrush='{DynamicResource RcFieldBorder}'
                      BorderThickness='1' CornerRadius='6' MinWidth='{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}'>
                <ScrollViewer MaxHeight='260'>
                  <ItemsPresenter/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType='ComboBoxItem'>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
    <Setter Property='Padding' Value='10,6,10,6'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='ComboBoxItem'>
          <Border x:Name='b' Background='Transparent' Padding='{TemplateBinding Padding}'>
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property='IsHighlighted' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcSelect}'/>
              <Setter Property='Foreground' Value='White'/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType='ListBox'>
    <Setter Property='Background' Value='Transparent'/>
    <Setter Property='BorderThickness' Value='0'/>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
  </Style>

  <Style TargetType='ListBoxItem'>
    <Setter Property='Foreground' Value='{DynamicResource RcText}'/>
    <Setter Property='Padding' Value='8,5,8,5'/>
    <Setter Property='Margin' Value='0,1,0,1'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='ListBoxItem'>
          <Border x:Name='b' Background='Transparent' CornerRadius='6' Padding='{TemplateBinding Padding}'>
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property='IsMouseOver' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcHover}'/>
            </Trigger>
            <Trigger Property='IsSelected' Value='True'>
              <Setter TargetName='b' Property='Background' Value='{DynamicResource RcSelect}'/>
              <Setter Property='Foreground' Value='White'/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType='Slider'>
    <Setter Property='Height' Value='24'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='Slider'>
          <Grid VerticalAlignment='Center'>
            <Border Height='4' CornerRadius='2' Background='{DynamicResource RcTrackBg}'/>
            <Track x:Name='PART_Track'>
              <Track.DecreaseRepeatButton>
                <RepeatButton Command='Slider.DecreaseLarge'>
                  <RepeatButton.Template>
                    <ControlTemplate TargetType='RepeatButton'>
                      <Border Height='4' CornerRadius='2' Background='{DynamicResource RcSelect}'/>
                    </ControlTemplate>
                  </RepeatButton.Template>
                </RepeatButton>
              </Track.DecreaseRepeatButton>
              <Track.IncreaseRepeatButton>
                <RepeatButton Command='Slider.IncreaseLarge'>
                  <RepeatButton.Template>
                    <ControlTemplate TargetType='RepeatButton'>
                      <Border Background='Transparent'/>
                    </ControlTemplate>
                  </RepeatButton.Template>
                </RepeatButton>
              </Track.IncreaseRepeatButton>
              <Track.Thumb>
                <Thumb Width='16' Height='16'>
                  <Thumb.Template>
                    <ControlTemplate TargetType='Thumb'>
                      <Ellipse Width='16' Height='16' Fill='White'
                               Stroke='{DynamicResource RcFieldBorder}' StrokeThickness='1'/>
                    </ControlTemplate>
                  </Thumb.Template>
                </Thumb>
              </Track.Thumb>
            </Track>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

</ResourceDictionary>";
}
