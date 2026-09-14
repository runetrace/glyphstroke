import GlyphstrokeCore

// Имена Gesture и Settings есть и в SwiftUI, и в нашем ядре. Один общий алиас
// на весь модуль приложения снимает неоднозначность: в коде интерфейса эти
// имена означают типы ядра. Отдельный файл — чтобы определение было ровно одно.
typealias Gesture = GlyphstrokeCore.Gesture
typealias Settings = GlyphstrokeCore.Settings
