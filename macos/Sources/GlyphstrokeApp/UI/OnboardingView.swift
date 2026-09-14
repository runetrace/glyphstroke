import SwiftUI
import AppKit
import GlyphstrokeMac

/// Окно первого запуска.
///
/// Без него программа выглядит сломанной: значок в строке меню появился, а
/// жесты не работают, и почему — неизвестно. Два разрешения macOS не выдаёт
/// программно ни при каких условиях, поэтому единственное, что можно сделать
/// хорошо, — объяснить по шагам и довести человека до нужной страницы настроек.
struct OnboardingView: View {
    /// Таймер нужен, потому что разрешения выдаются в другой программе:
    /// уведомления об этом система не присылает, остаётся спрашивать.
    @State private var inputMonitoring = Permissions.hasInputMonitoring
    @State private var accessibility = Permissions.hasAccessibility
    private let tick = Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()

    var onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(tr("Glyphstroke установлен"))
                    .font(.title2.bold())
                Text(tr("Осталось выдать два разрешения — иначе система не пустит программу к мыши."))
                    .foregroundStyle(.secondary)
            }

            step(number: 1,
                 title: tr("Мониторинг ввода"),
                 text: tr("Разрешает видеть движения мыши. Без него жесты не рисуются вовсе."),
                 done: inputMonitoring) {
                Permissions.requestInputMonitoring()
                Permissions.openInputMonitoringSettings()
            }

            step(number: 2,
                 title: tr("Универсальный доступ"),
                 text: tr("Разрешает выполнять действия жеста и узнавать, какое окно впереди."),
                 done: accessibility) {
                Permissions.requestAccessibility()
                Permissions.openAccessibilitySettings()
            }

            if inputMonitoring && accessibility {
                Label(tr("Всё выдано. Можно рисовать: зажмите правую кнопку и проведите мышью."),
                      systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            } else {
                Text(tr("В «Системных настройках» найдите Glyphstroke в списке и включите переключатель. ")
                     + tr("Если программы в списке нет, нажмите кнопку выше — она добавит её."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Divider()

            HStack {
                Text(tr("После выдачи разрешений программу нужно перезапустить."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Spacer()
                Button(tr("Перезапустить")) { Self.restart() }
                    .buttonStyle(.borderedProminent)
                    .tint(RcTheme.green)
                    .disabled(!(inputMonitoring && accessibility))
                Button(tr("Закрыть"), action: onDone)
            }
        }
        .padding(20)
        .frame(width: 520)
        .onReceive(tick) { _ in
            inputMonitoring = Permissions.hasInputMonitoring
            accessibility = Permissions.hasAccessibility
        }
    }

    @ViewBuilder
    private func step(number: Int, title: String, text: String, done: Bool,
                      action: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(done ? RcTheme.green : RcTheme.accent)
                    .frame(width: 24, height: 24)
                if done {
                    Image(systemName: "checkmark").foregroundStyle(.white).font(.caption.bold())
                } else {
                    Text("\(number)").foregroundStyle(.white).font(.caption.bold())
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(text).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            if !done {
                Button(tr("Открыть…"), action: action)
            }
        }
    }

    /// Перезапуск: система отдаёт уже выданные разрешения только новому
    /// процессу, и объяснять это словами бесполезно — проще сделать кнопкой.
    static func restart() {
        let url = Bundle.main.bundleURL
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.createsNewApplicationInstance = true
        NSWorkspace.shared.openApplication(at: url, configuration: configuration) { _, _ in
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }
}
