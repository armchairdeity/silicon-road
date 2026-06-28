import SwiftUI

struct ThumbnailItemView: View {
    let entry:      SidecarEntry
    let isSelected: Bool
    let isChecked:  Bool
    let onSelect:   () -> Void
    let onToggle:   () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Toggle("", isOn: Binding(get: { isChecked }, set: { _ in onToggle() }))
                .toggleStyle(.checkbox).labelsHidden()

            // Type icon
            ZStack {
                RoundedRectangle(cornerRadius: 4)
                    .fill(typeColor.opacity(0.15))
                    .frame(width: 36, height: 36)
                Image(systemName: typeIcon)
                    .font(.system(size: 16))
                    .foregroundStyle(typeColor)
            }

            // Labels
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.partNumber ?? entry.id)
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
                Text(entry.manufacturer ?? "Unknown")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()

            curationBadge
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(isSelected ? Color.accentColor.opacity(0.15) : Color.clear)
        .contentShape(Rectangle())
        .onTapGesture { onSelect() }
    }

    private var typeIcon: String {
        switch entry.assetType {
        case .pdf:     return "doc.fill"
        case .webpage: return "globe"
        case .unknown: return "questionmark.circle"
        }
    }

    private var typeColor: Color {
        switch entry.assetType {
        case .pdf:     return .red
        case .webpage: return .blue
        case .unknown: return .gray
        }
    }

    @ViewBuilder
    private var curationBadge: some View {
        switch entry.curationStatus {
        case .pending:
            Image(systemName: "clock")
                .font(.caption).foregroundStyle(.orange)
        case .accepted:
            Image(systemName: entry.vectoredAt != nil ? "checkmark.seal.fill" : "checkmark.circle")
                .font(.caption)
                .foregroundStyle(entry.vectoredAt != nil ? Color.purple : Color.green)
        case .rejected:
            Image(systemName: "xmark.circle")
                .font(.caption).foregroundStyle(.red)
        }
    }
}
