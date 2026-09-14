using System.Windows;

namespace Glyphstroke.App;

/// <summary>Точка входа.</summary>
/// <remarks>
/// Программа живёт в области уведомлений и без окна, поэтому режим завершения —
/// «только по команде»: иначе WPF закрыл бы приложение, как только человек
/// закроет последнее открытое окно, и жесты перестали бы работать молча.
///
/// Единственный экземпляр: два перехватчика мыши в системе — это два щелчка на
/// каждый жест и взаимные помехи, поэтому второй запуск не поднимает второй
/// экземпляр, а будит первый — тот показывает своё окно. Раньше здесь было лишь
/// сообщение «уже запущено», и человеку это выглядело как отказ открыть программу.
/// </remarks>
public static class Program
{
    private const string SingleInstanceName = "Glyphstroke.SingleInstance";
    private const string ShowSignalName = "Glyphstroke.Show";

    [STAThread]
    public static void Main()
    {
        using var single = new Mutex(initiallyOwned: true, SingleInstanceName, out bool first);
        if (!first)
        {
            // Уже запущено — просим работающий экземпляр показать окно и выходим.
            try
            {
                using var signal = EventWaitHandle.OpenExisting(ShowSignalName);
                signal.Set();
            }
            catch (WaitHandleCannotBeOpenedException)
            {
                // Первый экземпляр ещё не поднял сигнал — просто выходим.
            }
            return;
        }

        var application = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        Theme.Install(application, new Glyphstroke.Core.Store().LoadSettings().Theme);
        var tray = new TrayApp();
        application.Exit += (_, _) => tray.Dispose();
        tray.Start();

        // Сигнал от повторного запуска: показать окно программы в этом экземпляре.
        using var show = new EventWaitHandle(false, EventResetMode.AutoReset, ShowSignalName);
        var waiter = new Thread(() =>
        {
            while (show.WaitOne())
            {
                application.Dispatcher.Invoke(tray.ShowMainWindow);
            }
        })
        {
            IsBackground = true,
        };
        waiter.Start();

        application.Run();
    }
}
