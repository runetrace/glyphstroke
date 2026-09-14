using System.Globalization;
using System.Text.Json;

namespace Glyphstroke.Core;

/// <summary>Выпуск, о котором рассказал сервер.</summary>
public sealed record ReleaseInfo(string Version, string Url, string Notes);

/// <summary>Проверка обновлений: вышла ли версия новее установленной.</summary>
/// <remarks>
/// Программа не обновляется сама, и это решение, а не недоделка: она
/// перехватывает мышь, а тихая подмена работающей программы — совсем не то,
/// чего человек ждёт. Здесь только проверка; нашлось обновление — спрашиваем,
/// открыть ли страницу загрузки.
///
/// Источник — страница выпусков на GitHub и её открытый интерфейс: один запрос,
/// ответ в JSON, ни ключей, ни учётных записей.
///
/// Что с приватностью: проверка — обращение к чужому серверу, и наш адрес ему
/// становится известен. Поэтому она выключается настройкой, ходит не чаще раза
/// в сутки и ничего о системе не сообщает.
/// </remarks>
public static class UpdateCheck
{
    /// <summary>Где лежат выпуски по умолчанию — «владелец/хранилище».</summary>
    public const string DefaultRepository = "runetrace/glyphstroke";

    /// <summary>Чаще раза в сутки спрашивать незачем, а сервер чужой.</summary>
    public static readonly TimeSpan Interval = TimeSpan.FromHours(24);

    private static readonly HttpClient Client = new() { Timeout = TimeSpan.FromSeconds(10) };

    // --- сравнение версий ---

    /// <summary>
    /// <c>v0.7.1</c> → <c>[0, 7, 1]</c>. Хвосты вроде <c>-rc1</c> отбрасываются:
    /// черновой выпуск не должен выглядеть новее готового.
    /// </summary>
    public static int[] Parse(string text)
    {
        string head = (text ?? string.Empty).Split('-')[0];
        var numbers = new List<int>();
        foreach (var chunk in head.Split(new[] { '.', 'v', 'V', ' ' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (int.TryParse(chunk, NumberStyles.Integer, CultureInfo.InvariantCulture, out int value))
            {
                numbers.Add(value);
            }
        }
        return numbers.Count == 0 ? new[] { 0 } : numbers.Take(4).ToArray();
    }

    public static bool IsNewer(string candidate, string current)
    {
        int[] a = Parse(candidate), b = Parse(current);
        for (int i = 0; i < Math.Max(a.Length, b.Length); i++)
        {
            int left = i < a.Length ? a[i] : 0;
            int right = i < b.Length ? b[i] : 0;
            if (left != right)
            {
                return left > right;
            }
        }
        return false;
    }

    // --- запрос ---

    public static string ApiUrl(string repository) =>
        $"https://api.github.com/repos/{repository}/releases/latest";

    public static string ReleasePage(string repository) =>
        $"https://github.com/{repository}/releases/latest";

    /// <summary>Разобрать ответ сервера. Отдельно от сети — чтобы проверялось тестами.</summary>
    /// <param name="assetMarker">
    /// Если задан (например <c>-setup.exe</c>), версию берём из имени файла этого
    /// пакета в релизе, а не из тега. Тег в репозитории общий на три системы и
    /// уходит вперёд из-за выпусков под другие ОС; сравнивать надо с версией
    /// именно нашего пакета, иначе «есть обновление» показывалось бы зря.
    /// </param>
    public static ReleaseInfo? ReadRelease(string json, string? assetMarker = null)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            string tag = root.TryGetProperty("tag_name", out var tagNode) ? tagNode.GetString() ?? string.Empty
                : root.TryGetProperty("name", out var nameNode) ? nameNode.GetString() ?? string.Empty
                : string.Empty;
            tag = tag.Trim().TrimStart('v', 'V');
            if (tag.Length == 0)
            {
                return null;
            }
            string url = root.TryGetProperty("html_url", out var urlNode) ? urlNode.GetString() ?? string.Empty : string.Empty;
            string notes = root.TryGetProperty("body", out var bodyNode) ? (bodyNode.GetString() ?? string.Empty).Trim() : string.Empty;

            string version = tag;
            if (assetMarker is not null)
            {
                version = AssetVersion(root, assetMarker) ?? tag;
            }
            return new ReleaseInfo(version, url, notes);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>Версия из имени файла-пакета в релизе: <c>Glyphstroke-0.3.0.0-setup.exe</c> → <c>0.3.0.0</c>.</summary>
    private static string? AssetVersion(JsonElement root, string marker)
    {
        if (!root.TryGetProperty("assets", out var assets) || assets.ValueKind != JsonValueKind.Array)
        {
            return null;
        }
        foreach (var asset in assets.EnumerateArray())
        {
            string name = asset.TryGetProperty("name", out var n) ? n.GetString() ?? string.Empty : string.Empty;
            if (name.Contains(marker, StringComparison.OrdinalIgnoreCase))
            {
                var match = System.Text.RegularExpressions.Regex.Match(name, @"\d+(\.\d+)+");
                if (match.Success)
                {
                    return match.Value;
                }
            }
        }
        return null;
    }

    /// <summary>Спросить сервер. Нет сети — нет ответа, и это не ошибка.</summary>
    public static async Task<ReleaseInfo?> FetchAsync(string repository, string currentVersion,
                                                      string? assetMarker = null)
    {
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, ApiUrl(repository));
            request.Headers.Add("Accept", "application/vnd.github+json");
            // Без своего имени сервер отвечает отказом. Версию сообщаем ту же,
            // что и так видна в выпусках, — ничего нового этим не раскрываем.
            request.Headers.Add("User-Agent", $"Glyphstroke/{currentVersion}");
            using var response = await Client.SendAsync(request).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }
            return ReadRelease(await response.Content.ReadAsStringAsync().ConfigureAwait(false), assetMarker);
        }
        catch (Exception)
        {
            return null;
        }
    }

    // --- память между запусками ---

    /// <summary>
    /// Когда спрашивали и что ответили. Лежит рядом с настройками, но не в
    /// settings.yaml: это не настройка, а след работы программы, и возить его
    /// между машинами вместе с жестами незачем.
    /// </summary>
    private sealed class State
    {
        public double CheckedAt { get; set; }
        public string Version { get; set; } = string.Empty;
        public string Url { get; set; } = string.Empty;
        public string Notes { get; set; } = string.Empty;
    }

    private static string StatePath(Store store) => Path.Combine(store.Root, "update.json");

    private static State LoadState(Store store)
    {
        try
        {
            string path = StatePath(store);
            return File.Exists(path)
                ? JsonSerializer.Deserialize<State>(File.ReadAllText(path)) ?? new State()
                : new State();
        }
        catch (Exception)
        {
            return new State();
        }
    }

    public static bool Due(Store store, DateTimeOffset? now = null)
    {
        var state = LoadState(store);
        if (state.CheckedAt <= 0)
        {
            return true;
        }
        double passed = (now ?? DateTimeOffset.UtcNow).ToUnixTimeSeconds() - state.CheckedAt;
        // passed == 0 (проверка в ту же секунду) — это «только что спрашивали»,
        // значит ещё не пора. Отрицательное — время на машине перевели назад,
        // тогда лучше спросить, чем ждать сутки от будущего момента.
        return !(passed >= 0 && passed < Interval.TotalSeconds);
    }

    public static void Remember(Store store, ReleaseInfo? release, DateTimeOffset? now = null)
    {
        var state = LoadState(store);
        state.CheckedAt = (now ?? DateTimeOffset.UtcNow).ToUnixTimeSeconds();
        if (release is not null)
        {
            state.Version = release.Version;
            state.Url = release.Url;
            state.Notes = release.Notes;
        }
        try
        {
            store.PrepareDirectories();
            File.WriteAllText(StatePath(store),
                JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch (Exception)
        {
            // Нет прав на каталог — проверка просто будет ходить каждый запуск.
        }
    }

    /// <summary>Что известно из прошлой проверки и новее установленного, без сети.</summary>
    public static ReleaseInfo? Pending(Store store, string currentVersion)
    {
        var state = LoadState(store);
        if (state.Version.Length == 0 || !IsNewer(state.Version, currentVersion))
        {
            return null;
        }
        return new ReleaseInfo(state.Version, state.Url, state.Notes);
    }

    public static string Repository(Settings settings) =>
        string.IsNullOrWhiteSpace(settings.UpdateRepo) ? DefaultRepository : settings.UpdateRepo.Trim();
}
