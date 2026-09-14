using System;
using System.Windows;
using System.Windows.Controls;

namespace Glyphstroke.App;

/// <summary>Справка: список тем слева, текст справа — как в версии для Linux.</summary>
internal sealed class HelpWindow : Window
{
    public HelpWindow()
    {
        Title = L.Tr("Glyphstroke — справка");
        Width = 760;
        Height = 560;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        this.SetResourceReference(BackgroundProperty, "RcWindow");
        SourceInitialized += (_, _) => Theme.ApplyWindowChrome(this);

        var grid = new Grid { Margin = new Thickness(12) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(230) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var topics = Help.Topics();

        var list = new ListBox { BorderThickness = new Thickness(0) };
        foreach (var topic in topics)
        {
            list.Items.Add(new ListBoxItem { Content = topic.Title });
        }
        var leftCard = new Border
        {
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(8),
            Margin = new Thickness(0, 0, 12, 0),
            Child = list,
        };
        leftCard.SetResourceReference(Border.BackgroundProperty, "RcCard");
        leftCard.SetResourceReference(Border.BorderBrushProperty, "RcCardBorder");
        Grid.SetColumn(leftCard, 0);
        grid.Children.Add(leftCard);

        var contentPanel = new StackPanel { Margin = new Thickness(16, 4, 8, 4) };
        var scroll = new ScrollViewer
        {
            Content = contentPanel,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
        scroll.SetResourceReference(Control.BackgroundProperty, "RcWindow");
        Grid.SetColumn(scroll, 1);
        grid.Children.Add(scroll);

        list.SelectionChanged += (_, _) =>
        {
            contentPanel.Children.Clear();
            if (list.SelectedIndex < 0 || list.SelectedIndex >= topics.Count)
            {
                return;
            }
            var topic = topics[list.SelectedIndex];
            contentPanel.Children.Add(Theme.Header(topic.Title));
            foreach (var paragraph in topic.Body.Split("\n\n", StringSplitOptions.None))
            {
                contentPanel.Children.Add(Theme.Themed(new TextBlock
                {
                    Text = paragraph,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 10),
                }, "RcText"));
            }
        };
        list.SelectedIndex = 0;

        Content = grid;
    }
}
