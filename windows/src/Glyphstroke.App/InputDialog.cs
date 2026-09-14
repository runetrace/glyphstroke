using System.Windows;
using System.Windows.Controls;

namespace Glyphstroke.App;

/// <summary>Крошечное модальное окно ввода строки — своего InputBox в WPF нет.</summary>
internal static class InputDialog
{
    public static string? Ask(Window? owner, string title, string prompt, string initial = "")
    {
        var window = new Window
        {
            Title = title,
            Width = 360,
            SizeToContent = SizeToContent.Height,
            WindowStartupLocation = owner is null
                ? WindowStartupLocation.CenterScreen
                : WindowStartupLocation.CenterOwner,
            Owner = owner,
            ResizeMode = ResizeMode.NoResize,
            WindowStyle = WindowStyle.ToolWindow,
        };
        window.SetResourceReference(Control.BackgroundProperty, "RcWindow");
        window.SourceInitialized += (_, _) => Theme.ApplyWindowChrome(window);

        var panel = new StackPanel { Margin = new Thickness(16) };
        panel.Children.Add(Theme.Themed(new TextBlock { Text = prompt, TextWrapping = TextWrapping.Wrap }, "RcText"));

        var box = new TextBox { Text = initial, Margin = new Thickness(0, 8, 0, 12) };
        panel.Children.Add(box);

        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        var ok = new Button { Content = L.Tr("ОК"), Padding = new Thickness(16, 4, 16, 4), Margin = new Thickness(0, 0, 8, 0), IsDefault = true };
        var cancel = new Button { Content = L.Tr("Отмена"), Padding = new Thickness(16, 4, 16, 4), IsCancel = true };
        Theme.Primary(ok);
        string? result = null;
        ok.Click += (_, _) =>
        {
            result = box.Text;
            window.DialogResult = true;
        };
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        panel.Children.Add(buttons);

        window.Content = panel;
        box.Loaded += (_, _) => { box.SelectAll(); box.Focus(); };
        return window.ShowDialog() == true ? result : null;
    }
}
