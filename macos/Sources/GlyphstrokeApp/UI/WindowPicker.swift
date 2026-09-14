import AppKit
import GlyphstrokeMac

/// Кнопка-мишень: нажать, затем щёлкнуть по нужному окну — в поле добавится
/// строка «class:идентификатор.программы».
///
/// Так же, как в версиях для Linux и Windows, человеку не нужно знать
/// идентификатор пакета заранее. На маке щелчок ловит своё прозрачное окно
/// поверх всех экранов: следить за чужим щелчком со стороны нельзя — система
/// отдаёт такие события только наблюдателю, а обычный монитор не смог бы
/// помешать щелчку уйти в чужое приложение и переключить его на себя.
///
/// Всё происходит на главном потоке: и нажатие кнопки в редакторе, и щелчок в
/// окне-ловушке приходят оттуда, поэтому отдельной синхронизации здесь нет.
enum WindowPicker {
    private static var catcher: NSWindow?

    /// Показать мишень. `completed` получает имя программы или `nil`, если
    /// выбор отменили клавишей Esc.
    static func pick(completed: @escaping (String?) -> Void) {
        guard catcher == nil else { return }

        let frame = NSScreen.screens.reduce(NSRect.zero) { $0.union($1.frame) }
        let window = CatcherWindow(contentRect: frame, styleMask: .borderless,
                                   backing: .buffered, defer: false)
        window.level = .screenSaver
        window.isOpaque = false
        // Полностью прозрачное окно система считает «сквозным» и щелчки
        // пропускает насквозь, поэтому заливка почти невидимая, но не нулевая.
        window.backgroundColor = NSColor.black.withAlphaComponent(0.05)
        window.ignoresMouseEvents = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.onFinish = { point in
            finish()
            guard let point else {
                completed(nil)
                return
            }
            completed(WindowContext.app(at: point, excluding: ProcessInfo.processInfo.processIdentifier))
        }

        catcher = window
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        NSCursor.crosshair.push()
    }

    private static func finish() {
        NSCursor.pop()
        catcher?.orderOut(nil)
        catcher = nil
    }
}

/// Окно-ловушка щелчка. Безрамочное окно по умолчанию не становится ключевым,
/// а без этого до него не дойдёт Esc.
private final class CatcherWindow: NSWindow {
    var onFinish: ((CGPoint?) -> Void)?

    override var canBecomeKey: Bool { true }

    override func mouseDown(with event: NSEvent) {
        // Точку берём у CoreGraphics: она сразу в координатах перечня окон,
        // где начало в левом верхнем углу главного экрана.
        onFinish?(CGEvent(source: nil)?.location)
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 {  // Esc
            onFinish?(nil)
            return
        }
        super.keyDown(with: event)
    }
}
