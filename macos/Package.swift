// swift-tools-version:5.9
// Версия инструментов намеренно 5.9: при 6.0 включается строгая проверка
// параллелизма, а перехват событий здесь построен на C-обратном вызове с
// голым указателем — переучивать его на акторы до первого рабочего прогона
// смысла нет.
import PackageDescription

let package = Package(
    name: "Glyphstroke",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "glyphstroke", targets: ["GlyphstrokeApp"]),
        .library(name: "GlyphstrokeCore", targets: ["GlyphstrokeCore"]),
    ],
    dependencies: [
        // Файлы жестов общие с версией для Linux, поэтому нужен настоящий YAML,
        // а не самодельный разбор: там есть и блочные строки, и потоковые карты.
        .package(url: "https://github.com/jpsim/Yams.git", from: "5.0.0"),
    ],
    targets: [
        // Ядро без AppKit: распознавание и модель жестов. Отдельно, чтобы
        // проверять тестами без графики и разрешений системы.
        .target(
            name: "GlyphstrokeCore",
            dependencies: [.product(name: "Yams", package: "Yams")]
        ),
        // Всё, что говорит с macOS: перехват мыши, след, действия, разрешения.
        .target(
            name: "GlyphstrokeMac",
            dependencies: ["GlyphstrokeCore"]
        ),
        .executableTarget(
            name: "GlyphstrokeApp",
            dependencies: ["GlyphstrokeCore", "GlyphstrokeMac"],
            // Стартовый набор жестов едет с программой: пустой список на первом
            // запуске выглядит поломкой.
            resources: [.copy("Resources/gestures")]
        ),
        .testTarget(
            name: "GlyphstrokeCoreTests",
            dependencies: ["GlyphstrokeCore"]
        ),
        .testTarget(
            name: "GlyphstrokeMacTests",
            dependencies: ["GlyphstrokeCore", "GlyphstrokeMac"]
        ),
    ]
)
