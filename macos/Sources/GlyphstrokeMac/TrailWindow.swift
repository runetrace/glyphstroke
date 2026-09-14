import AppKit
import QuartzCore
import GlyphstrokeCore

/// След за курсором: прозрачное окно поверх всего экрана.
///
/// На маке это вся работа целиком — не нужно ни расширения оболочки, ни
/// отдельного процесса, как в Wayland: обычное окно без рамки, сквозное для
/// щелчков, живущее на всех рабочих столах.
///
/// Две вещи, о которые легко споткнуться.
///
/// **Системы координат разные.** События мыши приходят в координатах Quartz:
/// начало в левом верхнем углу главного экрана, Y растёт вниз. Окна же живут в
/// координатах AppKit: начало в левом нижнем, Y растёт вверх. Перевод — через
/// высоту главного экрана, и делать его надо в одном месте, иначе след поедет
/// на втором мониторе.
///
/// **Окно должно быть одно на все экраны.** Иначе росчерк, начатый на одном
/// мониторе и уведённый на другой, обрывался бы на границе.
public final class TrailWindow {
    private var window: NSWindow?
    private let shape = CAShapeLayer()
    private var points: [CGPoint] = []

    public var settings: OverlaySettings

    public init(settings: OverlaySettings = OverlaySettings()) {
        self.settings = settings
    }

    /// Начать новый росчерк.
    public func begin(at point: Point) {
        guard settings.enabled else { return }
        ensureWindow()
        points = [convert(point)]
        redraw()
        shape.removeAllAnimations()
        shape.opacity = Float(settings.opacity)
        window?.orderFrontRegardless()
    }

    /// Продолжить росчерк.
    public func extend(to point: Point) {
        guard settings.enabled, window != nil else { return }
        let converted = convert(point)
        // Точки в один пиксель только утяжеляют путь, рисунок от них не меняется.
        if let last = points.last, hypot(converted.x - last.x, converted.y - last.y) < 1.0 {
            return
        }
        points.append(converted)
        redraw()
    }

    /// Закончить росчерк: погасить след.
    public func end() {
        guard settings.enabled, let window else { return }
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = shape.opacity
        fade.toValue = 0.0
        fade.duration = Double(settings.fadeMs) / 1000.0
        fade.isRemovedOnCompletion = false
        fade.fillMode = .forwards
        shape.add(fade, forKey: "fade")

        let delay = DispatchTime.now() + .milliseconds(settings.fadeMs)
        DispatchQueue.main.asyncAfter(deadline: delay) { [weak self] in
            guard let self else { return }
            self.points = []
            self.shape.path = nil
            window.orderOut(nil)
        }
    }

    /// Убрать след немедленно — например, когда перехват встал на паузу.
    public func cancel() {
        points = []
        shape.path = nil
        shape.removeAllAnimations()
        window?.orderOut(nil)
    }

    // MARK: - Окно

    private func ensureWindow() {
        if let window, window.frame == Self.screensFrame() {
            return
        }
        // Экраны могли поменяться: подключили монитор, сменили разрешение.
        window?.orderOut(nil)

        let frame = Self.screensFrame()
        let panel = NSWindow(contentRect: frame, styleMask: .borderless,
                             backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.ignoresMouseEvents = true          // след не должен ловить щелчки
        panel.level = .screenSaver               // выше обычных окон и панели
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary,
                                    .fullScreenAuxiliary, .ignoresCycle]
        panel.setFrame(frame, display: false)

        let view = NSView(frame: NSRect(origin: .zero, size: frame.size))
        view.wantsLayer = true
        view.layer?.addSublayer(shape)
        shape.frame = view.bounds
        shape.fillColor = nil
        shape.lineJoin = .round
        shape.lineCap = .round
        panel.contentView = view

        window = panel
        applyStyle()
    }

    private func applyStyle() {
        shape.lineWidth = CGFloat(settings.width)
        shape.strokeColor = TrailWindow.color(from: settings.color).cgColor
        shape.opacity = Float(settings.opacity)
    }

    private func redraw() {
        applyStyle()
        guard points.count > 1 else {
            shape.path = nil
            return
        }
        let path = CGMutablePath()
        path.move(to: points[0])
        for point in points.dropFirst() {
            path.addLine(to: point)
        }
        shape.path = path
    }

    /// Прямоугольник, покрывающий все экраны сразу.
    static func screensFrame() -> NSRect {
        NSScreen.screens.reduce(NSRect.zero) { $0.isEmpty ? $1.frame : $0.union($1.frame) }
    }

    /// Quartz (начало сверху) → AppKit (начало снизу) и дальше в координаты окна.
    private func convert(_ point: Point) -> CGPoint {
        let primaryHeight = NSScreen.screens.first?.frame.maxY ?? 0
        let frame = window?.frame ?? Self.screensFrame()
        return CGPoint(x: point.x - frame.minX,
                       y: (primaryHeight - point.y) - frame.minY)
    }

    /// `#4da3ff` → цвет. Негодная запись не должна оставлять след невидимым,
    /// поэтому при разборе возвращаем заметный синий.
    public static func color(from text: String) -> NSColor {
        let fallback = NSColor(calibratedRed: 0.30, green: 0.64, blue: 1.0, alpha: 1.0)
        var hex = text.trimmingCharacters(in: .whitespaces)
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6, let value = UInt32(hex, radix: 16) else { return fallback }
        return NSColor(
            calibratedRed: CGFloat((value >> 16) & 0xFF) / 255.0,
            green: CGFloat((value >> 8) & 0xFF) / 255.0,
            blue: CGFloat(value & 0xFF) / 255.0,
            alpha: 1.0
        )
    }
}
