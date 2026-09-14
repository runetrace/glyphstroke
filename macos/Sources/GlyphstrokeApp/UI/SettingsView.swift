import SwiftUI
import AppKit
import GlyphstrokeCore
import GlyphstrokeMac


/// Настройки: кнопка-модификатор, вид следа, разрешения, автозапуск.
struct SettingsView: View {
    @ObservedObject var model: AppModel
    /// Пересчитывается при каждом появлении окна: разрешения человек выдаёт
    /// в другой программе, и узнать об этом можно только спросив заново.
    @State private var permissionsTick = 0

    var body: some View {
        Form {
            Section(tr("Разрешения")) {
                PermissionRow(title: tr("Мониторинг ввода"),
                              subtitle: tr("видеть движения мыши"),
                              granted: Permissions.hasInputMonitoring) {
                    Permissions.requestInputMonitoring()
                    Permissions.openInputMonitoringSettings()
                }
                PermissionRow(title: tr("Универсальный доступ"),
                              subtitle: tr("выполнять действия и знать активное окно"),
                              granted: Permissions.hasAccessibility) {
                    Permissions.requestAccessibility()
                    Permissions.openAccessibilitySettings()
                }
                Text(tr("После выдачи разрешения программу нужно перезапустить: ")
                     + tr("запущенной система продолжает отдавать прежний ответ."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button(tr("Проверить заново")) { permissionsTick += 1 }
            }
            .id(permissionsTick)

            Section(tr("Мышь")) {
                Picker(tr("Кнопка-модификатор"), selection: $model.settings.triggerButton) {
                    Text(tr("Правая")).tag("BTN_RIGHT")
                    Text(tr("Средняя")).tag("BTN_MIDDLE")
                }
                VStack(alignment: .leading) {
                    HStack {
                        Text(tr("Короткое движение — это щелчок"))
                        Spacer()
                        Text("\(Int(model.settings.minStrokePx)) \(tr("пикс."))")
                            .foregroundStyle(.secondary)
                    }
                    Slider(value: $model.settings.minStrokePx, in: 10...150, step: 5)
                }
                Picker(tr("Неопознанный росчерк"), selection: $model.settings.unrecognized) {
                    Text(tr("отдать программе")).tag("passthrough")
                    Text(tr("проглотить")).tag("swallow")
                }
                Text(tr("«Отдать программе» значит, что после неудачного росчерка откроется ")
                     + tr("обычное контекстное меню. Так понятнее: человек видит, что жест не вышел."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section(tr("След")) {
                Toggle(tr("Рисовать след"), isOn: $model.settings.overlay.enabled)
                ColorPicker(tr("Цвет"), selection: Binding(
                    get: { Color(nsColor: TrailWindow.color(from: model.settings.overlay.color)) },
                    set: { model.settings.overlay.color = Self.hex(from: $0) }
                ))
                Stepper("\(tr("Толщина:")) \(model.settings.overlay.width)",
                        value: $model.settings.overlay.width, in: 1...12)
                VStack(alignment: .leading) {
                    HStack {
                        Text(tr("Непрозрачность"))
                        Spacer()
                        Text(String(format: "%.0f%%", model.settings.overlay.opacity * 100))
                            .foregroundStyle(.secondary)
                    }
                    Slider(value: $model.settings.overlay.opacity, in: 0.1...1.0, step: 0.05)
                }
                VStack(alignment: .leading) {
                    HStack {
                        Text(tr("Гаснет за"))
                        Spacer()
                        Text("\(model.settings.overlay.fadeMs) \(tr("мс"))")
                            .foregroundStyle(.secondary)
                    }
                    Slider(value: Binding(
                        get: { Double(model.settings.overlay.fadeMs) },
                        set: { model.settings.overlay.fadeMs = Int($0) }
                    ), in: 0...1000, step: 20)
                }
            }

            Section(tr("Запуск")) {
                Toggle(tr("Запускать при входе в систему"), isOn: Binding(
                    get: { model.launchesAtLogin },
                    set: { model.setLaunchAtLogin($0) }
                ))
                Text(tr("Программа живёт в строке меню и без окна: без автозапуска ")
                     + tr("жесты перестанут работать после перезагрузки."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section(tr("Обновления")) {
                Toggle(tr("Проверять обновления"), isOn: $model.settings.checkUpdates)
                Text(tr("Раз в сутки программа спрашивает страницу выпусков, не вышла ли ")
                     + tr("версия новее. Сама она не обновляется: перехват мыши — не то место, ")
                     + tr("где уместна тихая подмена. Проверка обращается к чужому серверу и ")
                     + tr("ничего о вашей системе не сообщает."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                LabeledContent(tr("Где лежат выпуски")) {
                    TextField("", text: $model.settings.updateRepo,
                              prompt: Text(UpdateCheck.defaultRepository))
                        .frame(maxWidth: 240)
                }
            }

            Section(tr("Оформление")) {
                Picker(tr("Тема"), selection: $model.settings.theme) {
                    Text(tr("как в системе")).tag("system")
                    Text(tr("светлая")).tag("light")
                    Text(tr("тёмная")).tag("dark")
                }
                Picker(tr("Язык"), selection: $model.settings.language) {
                    Text(tr("как в системе")).tag("auto")
                    Text("English").tag("en")
                    Text("Русский").tag("ru")
                }
                Text(tr("Язык интерфейса сменится при следующем запуске."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section(tr("Файлы")) {
                LabeledContent(tr("Настройки и жесты")) {
                    Button(tr("Показать в Finder")) {
                        NSWorkspace.shared.open(model.store.root)
                    }
                }
                Text(model.store.root.path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .formStyle(.grouped)
        .onChange(of: model.settings) { _ in model.saveSettings() }
        .navigationTitle(tr("Настройки"))
    }

    /// Цвет из палитры — обратно в запись вида `#4da3ff`: в файле настроек
    /// живёт именно она, и она же понятна версии для Linux.
    static func hex(from color: Color) -> String {
        let nsColor = NSColor(color).usingColorSpace(.sRGB) ?? .systemBlue
        let red = Int((nsColor.redComponent * 255).rounded())
        let green = Int((nsColor.greenComponent * 255).rounded())
        let blue = Int((nsColor.blueComponent * 255).rounded())
        return String(format: "#%02x%02x%02x", red, green, blue)
    }
}

/// Строка разрешения: выдано или нет, и кнопка «выдать».
private struct PermissionRow: View {
    let title: String
    let subtitle: String
    let granted: Bool
    let action: () -> Void

    var body: some View {
        HStack {
            Image(systemName: granted ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .foregroundStyle(granted ? Color.green : Color.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if !granted {
                Button(tr("Выдать…"), action: action)
            }
        }
    }
}
