using Glyphstroke.Core;
using Xunit;

namespace Glyphstroke.Core.Tests;

/// <summary>Проверка обновлений: сравнение версий, разбор ответа, перерыв.</summary>
public class UpdateCheckTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "glyphstroke-update-" + Guid.NewGuid());

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    [Fact]
    public void VersionParsing()
    {
        Assert.Equal(new[] { 0, 7, 0 }, UpdateCheck.Parse("0.7.0"));
        Assert.Equal(new[] { 1, 2, 3 }, UpdateCheck.Parse("v1.2.3"));
        Assert.Equal(new[] { 0 }, UpdateCheck.Parse(""));
    }

    [Fact]
    public void PrereleaseIsNotNewerThanRelease()
    {
        // «0.8.0-rc1» не должен выглядеть новее готовой 0.8.0.
        Assert.False(UpdateCheck.IsNewer("0.8.0-rc1", "0.8.0"));
        Assert.True(UpdateCheck.IsNewer("0.8.0", "0.7.9"));
        Assert.False(UpdateCheck.IsNewer("0.7.0", "0.7.0"));
        Assert.True(UpdateCheck.IsNewer("1.0", "0.9.9"));
        Assert.False(UpdateCheck.IsNewer("0.9", "0.9.1"));
    }

    [Fact]
    public void ReleaseIsReadFromTheAnswer()
    {
        var release = UpdateCheck.ReadRelease(
            """{"tag_name": "v0.9.0", "html_url": "https://пример/0.9.0", "body": " что нового "}""");
        Assert.Equal("0.9.0", release?.Version);
        Assert.Equal("https://пример/0.9.0", release?.Url);
        Assert.Equal("что нового", release?.Notes);
    }

    [Fact]
    public void AnswerWithoutATagIsIgnored()
    {
        Assert.Null(UpdateCheck.ReadRelease("""{"message": "Not Found"}"""));
        Assert.Null(UpdateCheck.ReadRelease("не json"));
    }

    [Fact]
    public void VersionComesFromTheAssetWhenAsked()
    {
        // Общий тег на три системы (v0.3.2) не должен выдавать себя за версию
        // винды: её берём из имени установщика в релизе.
        const string json = """
        {"tag_name": "v0.3.2", "html_url": "u", "body": "",
         "assets": [{"name": "glyphstroke_0.8.10_all.deb"},
                    {"name": "Glyphstroke-0.3.0.0-setup.exe"}]}
        """;
        Assert.Equal("0.3.0.0", UpdateCheck.ReadRelease(json, "-setup.exe")?.Version);
        // Без маркера — прежнее поведение, версия из тега.
        Assert.Equal("0.3.2", UpdateCheck.ReadRelease(json)?.Version);
        // Установленная 0.3.0 и .exe 0.3.0.0 — обновления нет.
        Assert.False(UpdateCheck.IsNewer("0.3.0.0", "0.3.0"));
    }

    [Fact]
    public void IntervalIsRespected()
    {
        var store = new Store(_root);
        Assert.True(UpdateCheck.Due(store), "ни разу не спрашивали");

        UpdateCheck.Remember(store, null);
        Assert.False(UpdateCheck.Due(store));
        Assert.True(UpdateCheck.Due(store, DateTimeOffset.UtcNow.Add(UpdateCheck.Interval).AddMinutes(1)));
        // время перевели назад: лучше спросить, чем ждать сутки от будущего
        Assert.True(UpdateCheck.Due(store, DateTimeOffset.UtcNow.AddHours(-5)));
    }

    [Fact]
    public void PendingKeepsOnlyNewerVersions()
    {
        var store = new Store(_root);
        UpdateCheck.Remember(store, new ReleaseInfo("9.9.9", "https://пример/9.9.9", string.Empty));

        Assert.Equal("9.9.9", UpdateCheck.Pending(store, "0.1.0")?.Version);
        Assert.Null(UpdateCheck.Pending(store, "9.9.9"));     // своя же версия — не новость
        Assert.Null(UpdateCheck.Pending(store, "10.0.0"));
    }

    [Fact]
    public void RepositoryComesFromSettings()
    {
        var settings = new Settings();
        Assert.Equal(UpdateCheck.DefaultRepository, UpdateCheck.Repository(settings));
        settings.UpdateRepo = " кто-то/что-то ";
        Assert.Equal("кто-то/что-то", UpdateCheck.Repository(settings));
        Assert.EndsWith("/releases/latest", UpdateCheck.ReleasePage("a/b"));
        Assert.StartsWith("https://api.github.com/repos/", UpdateCheck.ApiUrl("a/b"));
    }
}
