import SwiftUI
import GlyphstrokeCore

/// Поле для рисования образцов жеста.
///
/// Образец — это второй способ задать фигуру, кроме букв направлений. Он нужен
/// там, где буквами не опишешь: петля, галочка, вопросительный знак. Чем больше
/// образцов, тем терпимее распознавание, поэтому рисовать один и тот же знак
/// несколько раз — это не лишняя работа, а обучение.
struct StrokeCanvas: View {
    @Binding var templates: [[Point]]

    @State private var current: [Point] = []
    @State private var drawing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color(nsColor: .textBackgroundColor))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.4)))

                Canvas { context, _ in
                    guard current.count > 1 else { return }
                    var path = Path()
                    path.move(to: CGPoint(x: current[0].x, y: current[0].y))
                    for point in current.dropFirst() {
                        path.addLine(to: CGPoint(x: point.x, y: point.y))
                    }
                    context.stroke(path, with: .color(.accentColor),
                                   style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
                }

                if current.isEmpty {
                    Text(tr("Нарисуйте здесь фигуру жеста"))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .padding(12)
                }
            }
            .frame(height: 180)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        if !drawing {
                            drawing = true
                            current = []
                        }
                        current.append(Point(value.location.x, value.location.y))
                    }
                    .onEnded { _ in drawing = false }
            )

            HStack {
                if current.count > 1 {
                    Text("\(tr("Код:")) \(DirectionCode.of(current))")
                        .font(.callout.monospaced())
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(tr("Очистить")) { current = [] }
                    .disabled(current.isEmpty)
                Button(tr("Добавить образец")) {
                    templates.append(current)
                    current = []
                }
                .disabled(current.count < 2)
            }

            if !templates.isEmpty {
                Text(tr("Образцы"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(templates.indices, id: \.self) { index in
                            TemplateThumbnail(points: templates[index]) {
                                templates.remove(at: index)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }
}

/// Маленькая картинка образца с крестиком удаления.
private struct TemplateThumbnail: View {
    let points: [Point]
    let onDelete: () -> Void

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Canvas { context, size in
                let fitted = Self.fit(points, into: size)
                guard fitted.count > 1 else { return }
                var path = Path()
                path.move(to: fitted[0])
                for point in fitted.dropFirst() {
                    path.addLine(to: point)
                }
                context.stroke(path, with: .color(.primary),
                               style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
            }
            .frame(width: 64, height: 64)
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.3)))

            Button(action: onDelete) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.borderless)
            .offset(x: 6, y: -6)
        }
    }

    /// Вписать росчерк в квадратик, сохранив пропорции: иначе прямая линия
    /// растянулась бы в квадрат и образец было бы не узнать.
    static func fit(_ points: [Point], into size: CGSize) -> [CGPoint] {
        guard !points.isEmpty else { return [] }
        let box = Geometry.boundingBox(points)
        let padding = 8.0
        let scale = min((size.width - padding * 2) / max(box.width, 1),
                        (size.height - padding * 2) / max(box.height, 1))
        let offsetX = (size.width - box.width * scale) / 2
        let offsetY = (size.height - box.height * scale) / 2
        return points.map {
            CGPoint(x: ($0.x - box.x) * scale + offsetX,
                    y: ($0.y - box.y) * scale + offsetY)
        }
    }
}
