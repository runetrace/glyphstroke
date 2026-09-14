import AppKit
import GlyphstrokeCore

/// Меню под жестом: список пунктов у курсора, выбор — щелчком.
///
/// На Linux меню выбирается движением при зажатой кнопке — там демон держит
/// мышь. На маке жест завершается на отпускании кнопки, держать нечего,
/// поэтому пункт выбирается обычным щелчком: то же меню под жестом, только
/// подтверждение привычнее для системы.
///
/// Меню родное, `NSMenu`, а не своё окно с кнопками. Это не лень: от системы
/// оно получает тему, прокрутку длинного списка, выбор стрелками, закрытие по
/// Esc и по щелчку мимо. Своя реализация всё это потеряла бы, а меню под
/// жестом — единственное место, где человек видит нарисованное им же и должен
/// узнать привычный элемент, а не самоделку.
public final class GestureMenu: NSObject {
    /// Пока меню открыто, ссылку держим здесь: иначе объект уйдёт вместе с
    /// последней ссылкой и цели пунктов останутся без адресата.
    private static var live: GestureMenu?

    private let menu = NSMenu()
    private let items: [MenuItem]
    private let run: ([Action]) -> Void
    private var timeout: Timer?

    private init(items: [MenuItem], run: @escaping ([Action]) -> Void) {
        self.items = items
        self.run = run
        super.init()

        menu.autoenablesItems = false
        for (index, item) in items.enumerated() {
            let title = item.name.trimmingCharacters(in: .whitespaces)
            let entry = NSMenuItem(title: title.isEmpty ? "—" : title,
                                   action: #selector(pick(_:)), keyEquivalent: "")
            entry.target = self
            entry.tag = index
            entry.isEnabled = true
            menu.addItem(entry)
        }
    }

    /// Показать меню у курсора.
    ///
    /// Вызывать только с главного потока и только после того, как перехват
    /// вернул управление: `popUp` крутит собственный цикл событий и до закрытия
    /// меню не отдаёт поток никому.
    @discardableResult
    public static func show(items: [MenuItem], timeoutMs: Int,
                            run: @escaping ([Action]) -> Void) -> Bool {
        let usable = items.filter {
            !$0.name.trimmingCharacters(in: .whitespaces).isEmpty || !$0.actions.isEmpty
        }
        guard !usable.isEmpty else { return false }

        let controller = GestureMenu(items: usable, run: run)
        GestureMenu.live = controller
        controller.armTimeout(ms: timeoutMs)

        // Программа живёт в строке меню и обычно не активна. Без активации
        // меню откроется, но не возьмёт клавиатуру, и стрелками по нему не
        // пройтись.
        NSApp.activate(ignoringOtherApps: true)
        let shown = controller.menu.popUp(positioning: nil, at: NSEvent.mouseLocation, in: nil)
        controller.timeout?.invalidate()
        GestureMenu.live = nil
        return shown
    }

    /// Меню, про которое забыли, не должно висеть поверх всех окон вечно.
    ///
    /// Таймер идёт через `RunLoop` в общем режиме, а не через очередь: пока
    /// меню открыто, система крутит цикл в режиме слежения за событиями, и
    /// отложенная задача в очереди до закрытия меню просто не выполнится.
    private func armTimeout(ms: Int) {
        let seconds = Double(max(1000, ms)) / 1000.0
        let timer = Timer(timeInterval: seconds, repeats: false) { [weak self] _ in
            self?.menu.cancelTracking()
        }
        RunLoop.main.add(timer, forMode: .common)
        timeout = timer
    }

    @objc private func pick(_ sender: NSMenuItem) {
        timeout?.invalidate()
        guard items.indices.contains(sender.tag) else { return }
        let actions = items[sender.tag].actions
        // Действия выполняем после закрытия меню: нажатие клавиш при живом
        // меню ушло бы в само меню, а не в приложение под ним.
        DispatchQueue.main.async { [run] in
            run(actions)
        }
    }
}
