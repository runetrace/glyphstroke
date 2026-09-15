using Glyphstroke.Core;
using Xunit;

namespace Glyphstroke.Core.Tests;

/// <summary>Чтение и запись файлов: формат общий с другими системами.</summary>
public class StoreTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "glyphstroke-tests-" + Guid.NewGuid());

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    private Store NewStore() => new(_root);

    [Fact]
    public void ProfilesKeepSeparateGestureSets()
    {
        var store = NewStore();
        // Основной набор — папка gestures.
        store.Save(new Gesture { Name = "Базовый" });
        Assert.Single(store.LoadGestures());

        // Новый набор пуст, если копировать неоткуда...
        store.CreateProfile("Работа");
        store.ActiveProfile = "Работа";
        Assert.Empty(store.LoadGestures());
        store.Save(new Gesture { Name = "Рабочий" });

        // ...основной при этом не тронут.
        store.ActiveProfile = "";
        Assert.Equal("Базовый", store.LoadGestures().Single().Name);

        // Набор виден в списке; копирование переносит жесты.
        Assert.Contains("Работа", store.AvailableProfiles());
        string copy = store.CreateProfile("Копия", copyFrom: "Работа");
        store.ActiveProfile = copy;
        Assert.Equal("Рабочий", store.LoadGestures().Single().Name);

        // Удаление убирает набор из списка.
        store.RemoveProfile("Работа");
        Assert.DoesNotContain("Работа", store.AvailableProfiles());
    }

    [Fact]
    public void GestureSurvivesSaveAndLoad()
    {
        var store = NewStore();
        var gesture = new Gesture
        {
            Name = "Назад",
            Description = "Росчерк влево",
            Directions = { "L", "L-DL" },
            Apps = { "class:chrome.exe" },
            RotationTolerance = 25,
            Actions = { new GestureAction("standard", "back") },
            Templates = { new List<Point> { new(0, 0), new(10.5, 20.25) } },
        };
        store.Save(gesture);

        var loaded = store.LoadGestures().Single();
        Assert.Equal("Назад", loaded.Name);
        Assert.Equal(new[] { "L", "L-DL" }, loaded.Directions);
        Assert.Equal(new[] { "class:chrome.exe" }, loaded.Apps);
        Assert.Equal(25, loaded.RotationTolerance);
        Assert.Equal("standard", loaded.Actions.Single().Type);
        Assert.Equal("back", loaded.Actions.Single().Value);
        Assert.Equal(2, loaded.Templates.Single().Count);
        // Точки округляются до десятых — этого хватает распознаванию и не
        // раздувает файл.
        Assert.Equal(10.5, loaded.Templates.Single()[1].X, 1);
    }

    [Fact]
    public void GestureWithoutMenuKeepsNoMenuKey()
    {
        var store = NewStore();
        store.Save(new Gesture { Name = "Простой" });
        string text = File.ReadAllText(store.LoadGestures().Single().FilePath!);
        Assert.DoesNotContain("menu:", text);
    }

    [Fact]
    public void BrokenFileDoesNotBreakTheRest()
    {
        var store = NewStore();
        store.Save(new Gesture { Name = "Целый" });
        File.WriteAllText(Path.Combine(store.GesturesDirectory, "битый.yaml"), "{ не yaml: [");

        var gestures = store.LoadGestures();
        Assert.Single(gestures);
        Assert.Equal("Целый", gestures[0].Name);
    }

    [Fact]
    public void SettingsSurviveSaveAndLoad()
    {
        var store = NewStore();
        var settings = new Settings
        {
            TriggerButton = "BTN_MIDDLE",
            MinStrokePx = 55,
            Unrecognized = "swallow",
            CheckUpdates = false,
            UpdateRepo = "кто-то/что-то",
        };
        settings.Overlay.Color = "#ff8800";
        settings.Overlay.FadeMs = 300;
        settings.ExcludedApps.Add("class:game.exe");
        store.SaveSettings(settings);

        var loaded = NewStore().LoadSettings();
        Assert.Equal("BTN_MIDDLE", loaded.TriggerButton);
        Assert.Equal(55, loaded.MinStrokePx);
        Assert.Equal("swallow", loaded.Unrecognized);
        Assert.False(loaded.CheckUpdates);
        Assert.Equal("кто-то/что-то", loaded.UpdateRepo);
        Assert.Equal("#ff8800", loaded.Overlay.Color);
        Assert.Equal(300, loaded.Overlay.FadeMs);
        Assert.Equal(new[] { "class:game.exe" }, loaded.ExcludedApps);
    }

    [Fact]
    public void ForeignKeysSurviveARoundTrip()
    {
        // Файл настроек ездит между системами: ключи Linux (устройства ввода,
        // клавиша тачпада) здесь не разбираются, но затирать их нельзя.
        var store = NewStore();
        store.PrepareDirectories();
        File.WriteAllText(store.SettingsPath,
            "language: \"ru\"\ntouchpad_key: \"KEY_LEFTMETA\"\ndevice_include:\n  - \"^Logitech\"\n");

        var settings = store.LoadSettings();
        store.SaveSettings(settings);

        string text = File.ReadAllText(store.SettingsPath);
        Assert.Contains("touchpad_key", text);
        Assert.Contains("device_include", text);
        Assert.Contains("Logitech", text);
    }

    [Fact]
    public void StarterGesturesArriveOnlyOnce()
    {
        var source = Path.Combine(_root, "образцы");
        Directory.CreateDirectory(source);
        File.WriteAllText(Path.Combine(source, "nazad.yaml"),
            "name: \"Назад\"\nenabled: true\ndirections: [L]\nactions:\n  - {type: \"standard\", value: \"back\"}\n");

        var store = NewStore();
        Assert.Equal(1, store.InstallStarterGestures(source));
        Assert.Equal(0, store.InstallStarterGestures(source));
        Assert.Single(store.LoadGestures());
    }

    [Fact]
    public void NewGestureNeverOverwritesAnExistingFile()
    {
        // Баг: добавили жест «Новый жест», переименовали его (слаг имени
        // освободился), добавили второй «Новый жест» — он писался в тот же файл
        // и молча затирал первый. Новый жест обязан получить свободное имя файла.
        var store = NewStore();

        var first = new Gesture { Name = "Новый жест" };
        store.Save(first);
        first.Name = "Разворот";
        store.Save(first); // тот же файл (FilePath уже задан), просто переименование

        var second = new Gesture { Name = "Новый жест" };
        store.Save(second);

        Assert.NotEqual(first.FilePath, second.FilePath);
        var names = store.LoadGestures().Select(gesture => gesture.Name).ToList();
        Assert.Equal(2, names.Count);
        Assert.Contains("Разворот", names);
        Assert.Contains("Новый жест", names);
    }

    [Fact]
    public void RenamingAGestureRenamesItsFile()
    {
        // Переименовали жест — файл должен получить имя по новому названию,
        // старый файл исчезает (иначе на диске остаётся «новый-жест-2.yaml»).
        var store = NewStore();
        var gesture = new Gesture { Name = "Назад" };
        string first = store.Save(gesture);
        Assert.Equal("назад.yaml", Path.GetFileName(first));

        gesture.Name = "Вперёд";
        string second = store.Save(gesture);
        Assert.Equal("вперёд.yaml", Path.GetFileName(second));
        Assert.False(File.Exists(first));           // старый файл удалён
        Assert.True(File.Exists(second));
        Assert.Equal("Вперёд", store.LoadGestures().Single().Name);
    }

    [Fact]
    public void ResavingWithoutRenameKeepsTheFile()
    {
        // Пересохранение без смены имени не должно трогать имя файла
        // (в т.ч. уникализированное «-2»).
        var store = NewStore();
        store.Save(new Gesture { Name = "Копия" });        // копия.yaml
        var second = new Gesture { Name = "Копия" };
        string p = store.Save(second);                     // копия-2.yaml
        Assert.Equal("копия-2.yaml", Path.GetFileName(p));

        second.Enabled = false;
        string again = store.Save(second);                 // имя не менялось
        Assert.Equal(p, again);                            // тот же файл
    }

    [Fact]
    public void SlugKeepsLettersAndLowersThem()
    {
        Assert.Equal("новая-вкладка", Store.Slug("Новая вкладка"));
        Assert.Equal("gesture", Store.Slug("   "));
    }
}
