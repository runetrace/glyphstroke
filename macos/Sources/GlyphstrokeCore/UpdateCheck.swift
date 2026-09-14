import Foundation

/// Проверка обновлений: вышла ли версия новее установленной.
///
/// Программа не обновляется сама, и это решение, а не недоделка: она
/// перехватывает мышь, а тихая подмена работающей программы — совсем не то,
/// чего человек ждёт. Здесь только проверка; нашлось обновление — окно
/// спрашивает, открыть ли страницу загрузки.
///
/// Источник — страница выпусков на GitHub и её открытый интерфейс: один
/// запрос, ответ в JSON, ни ключей, ни учётных записей. Своего сервера у
/// проекта нет, а заводить его ради номера версии незачем.
///
/// Что с приватностью: проверка — обращение к чужому серверу, и наш адрес ему
/// становится известен. Поэтому она выключается в настройках, ходит не чаще
/// раза в сутки и ничего о системе не сообщает.
public enum UpdateCheck {
    /// Где лежат выпуски по умолчанию — «владелец/хранилище».
    public static let defaultRepository = "runetrace/glyphstroke"

    /// Чаще раза в сутки спрашивать незачем, а сервер чужой.
    public static let interval: TimeInterval = 24 * 3600

    public struct Release: Equatable {
        public let version: String
        public let url: URL?
        public let notes: String
    }

    // MARK: - Сравнение версий

    /// `v0.7.1` → `[0, 7, 1]`. Хвосты вроде `-rc1` отбрасываются: черновой
    /// выпуск не должен выглядеть новее готового.
    public static func parse(_ text: String) -> [Int] {
        let head = text.split(separator: "-", maxSplits: 1).first.map(String.init) ?? text
        let numbers = head.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
        return numbers.isEmpty ? [0] : Array(numbers.prefix(4))
    }

    public static func isNewer(_ candidate: String, than current: String) -> Bool {
        let a = parse(candidate), b = parse(current)
        for index in 0..<max(a.count, b.count) {
            let left = index < a.count ? a[index] : 0
            let right = index < b.count ? b[index] : 0
            if left != right { return left > right }
        }
        return false
    }

    // MARK: - Запрос

    public static func apiURL(repository: String) -> URL? {
        URL(string: "https://api.github.com/repos/\(repository)/releases/latest")
    }

    public static func releasePage(repository: String) -> URL? {
        URL(string: "https://github.com/\(repository)/releases/latest")
    }

    /// Разобрать ответ сервера. Отдельно от сети, чтобы проверялось тестами.
    public static func release(fromJSON data: Data) -> Release? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let tag = (object["tag_name"] as? String) ?? (object["name"] as? String) ?? ""
        let clean = tag.trimmingCharacters(in: CharacterSet(charactersIn: "vV "))
        guard !clean.isEmpty else { return nil }
        return Release(
            version: clean,
            url: (object["html_url"] as? String).flatMap(URL.init(string:)),
            notes: (object["body"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        )
    }

    /// Спросить сервер. Ошибка сети — не ошибка программы: ответом будет `nil`.
    public static func fetch(repository: String,
                             session: URLSession = .shared,
                             completion: @escaping (Release?) -> Void) {
        guard let url = apiURL(repository: repository) else {
            completion(nil)
            return
        }
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        // Без своего имени сервер отвечает отказом. Версию сообщаем ту же,
        // что и так видна в выпусках, — ничего нового этим не раскрываем.
        request.setValue("Glyphstroke/\(Bundle.main.shortVersion)", forHTTPHeaderField: "User-Agent")

        session.dataTask(with: request) { data, _, _ in
            completion(data.flatMap(release(fromJSON:)))
        }.resume()
    }

    // MARK: - Память между запусками

    /// Когда спрашивали в последний раз и что ответили.
    ///
    /// Живёт в UserDefaults, а не в settings.yaml: это не настройка, а след
    /// работы программы, и переносить его между машинами вместе с жестами
    /// незачем.
    private enum Keys {
        static let checkedAt = "update.checkedAt"
        static let version = "update.version"
        static let url = "update.url"
        static let notes = "update.notes"
    }

    public static func due(now: Date = Date(), defaults: UserDefaults = .standard) -> Bool {
        let checked = defaults.double(forKey: Keys.checkedAt)
        guard checked > 0 else { return true }
        let passed = now.timeIntervalSince1970 - checked
        // Время на машине могли перевести назад — тогда лучше спросить, чем
        // ждать сутки от будущего момента.
        return !(passed > 0 && passed < interval)
    }

    public static func remember(_ release: Release?, now: Date = Date(),
                                defaults: UserDefaults = .standard) {
        defaults.set(now.timeIntervalSince1970, forKey: Keys.checkedAt)
        guard let release else { return }
        defaults.set(release.version, forKey: Keys.version)
        defaults.set(release.url?.absoluteString ?? "", forKey: Keys.url)
        defaults.set(release.notes, forKey: Keys.notes)
    }

    /// Что известно из прошлой проверки и новее установленного, без сети.
    public static func pending(currentVersion: String,
                               defaults: UserDefaults = .standard) -> Release? {
        guard let version = defaults.string(forKey: Keys.version), !version.isEmpty,
              isNewer(version, than: currentVersion) else {
            return nil
        }
        return Release(version: version,
                       url: (defaults.string(forKey: Keys.url)).flatMap(URL.init(string:)),
                       notes: defaults.string(forKey: Keys.notes) ?? "")
    }
}

public extension Bundle {
    /// Номер версии программы — тот, что видно в «О программе».
    var shortVersion: String {
        (infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0"
    }
}
