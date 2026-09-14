import SwiftUI

/// Справка: список тем слева, текст справа — как в версиях для Linux и Windows.
///
/// Текст лежит в программе, а не открывается ссылкой в браузере: справка нужна
/// ровно тогда, когда что-то не работает, и отправлять человека в сеть за
/// объяснением, почему у него не двигается мышь, — плохая идея.
struct HelpView: View {
    @State private var selected: String?

    private let topics = Help.topics()

    var body: some View {
        NavigationSplitView {
            List(topics, selection: $selected) { topic in
                Text(topic.title).tag(topic.id)
            }
            .frame(minWidth: 220)
        } detail: {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let topic = current {
                        Text(topic.title)
                            .font(.title2.weight(.semibold))
                        ForEach(Array(paragraphs(of: topic).enumerated()), id: \.offset) { entry in
                            Text(entry.element)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
            }
        }
        .onAppear {
            if selected == nil { selected = topics.first?.id }
        }
    }

    private var current: Help.Topic? {
        topics.first { $0.id == selected } ?? topics.first
    }

    /// Абзацы разделены пустой строкой — тем же способом, что в остальных
    /// версиях, чтобы текст справки правился в одном месте и одинаково.
    private func paragraphs(of topic: Help.Topic) -> [String] {
        topic.body
            .components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
}
