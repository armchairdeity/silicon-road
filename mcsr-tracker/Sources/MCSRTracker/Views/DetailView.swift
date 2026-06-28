import SwiftUI
import AppKit

struct DetailView: View {
    let entry: SidecarEntry
    let store: SidecarStore
    let cache: AssetCache

    private var trust: DomainTrust.Status { DomainTrust.check(urlString: entry.effectiveUrl) }

    var body: some View {
        VSplitView {
            // ── Top half: metadata + action row ──────────────────────────────
            VStack(alignment: .leading, spacing: 0) {
                headerBar
                Divider()
                ScrollView { metadataBlock.padding() }
                Divider()
                actionRow
            }
            .frame(minHeight: 240)

            // ── Bottom half: asset preview ────────────────────────────────────
            PreviewView(entry: entry, cache: cache)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    // MARK: - Header

    private var headerBar: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text(entry.partNumber ?? "Unknown Part").font(.title2.bold())
                Text(entry.manufacturer ?? "Unknown Manufacturer")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer()
            if let urlStr = entry.effectiveUrl, let url = URL(string: urlStr) {
                Button {
                    if let local = cache.localURL(for: entry) { NSWorkspace.shared.open(local) }
                    else { NSWorkspace.shared.open(url) }
                } label: {
                    Label("Open in \(defaultAppName(for: entry))",
                          systemImage: "arrow.up.right.square")
                        .font(.caption)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding()
    }

    // MARK: - Metadata

    @ViewBuilder
    private var metadataBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            row("Asset Type",    entry.assetType.rawValue)
            row("Content Type",  entry.datasheetContentType ?? "—")
            row("Security",      trust.label,
                color: trust == .trusted ? .green : trust == .unverified ? .orange : .secondary)

            if let urlStr = entry.effectiveUrl {
                urlRow(urlStr)
            }

            if let summary = entry.technicalSummary, !summary.isEmpty {
                Divider()
                row("Summary", summary, multiline: true)
            }

            if let specs = entry.keySpecs?.prefix(6), !specs.isEmpty {
                Divider()
                HStack(alignment: .top) {
                    label("Key Specs")
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(specs), id: \.self) { spec in
                            Text("• \(spec)").font(.caption)
                        }
                    }
                }
            }

            Divider()
            if let d = entry.rejectedAt  { row("Rejected",  d.formatted()) }
            if let d = entry.vectoredAt  { row("Vectored",  d.formatted()) }
            row("Status", entry.curationStatus.rawValue.capitalized)
        }
    }

    private func urlRow(_ urlStr: String) -> some View {
        HStack(alignment: .top) {
            label("URL")
            VStack(alignment: .leading, spacing: 2) {
                Text(urlStr).font(.caption.monospaced()).lineLimit(2).textSelection(.enabled)
                HStack(spacing: 4) {
                    if let valid = entry.datasheetUrlValid {
                        Image(systemName: valid ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundStyle(valid ? .green : .red)
                        Text(valid ? "Reachable" : "Broken")
                    } else {
                        Image(systemName: "questionmark.circle").foregroundStyle(.orange)
                        Text("Not validated")
                    }
                }
                .font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Action Row

    private var actionRow: some View {
        HStack(spacing: 12) {
            Spacer()
            actionBtn("Accept", key: "a", fg: .green)  { store.accept(ids: [entry.id]) }
            actionBtn("Reject", key: "r", fg: .red)    { store.reject(ids: [entry.id]) }
            actionBtn("Keep",   key: "k", fg: .primary) { store.keep(ids: [entry.id]) }
            actionBtn("Delete", key: "d", fg: .orange) { store.delete(ids: [entry.id]) }
            Spacer()
        }
        .padding(.vertical, 10)
        .background(.bar)
    }

    @ViewBuilder
    private func actionBtn(_ title: String, key: KeyEquivalent, fg: Color,
                           action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.system(size: 13, weight: .medium)).frame(width: 72)
        }
        .keyboardShortcut(key, modifiers: [])
        .foregroundStyle(fg)
        .buttonStyle(.bordered)
    }

    // MARK: - Row Helpers

    private func label(_ text: String) -> some View {
        Text(text).font(.caption).foregroundStyle(.secondary).frame(width: 100, alignment: .trailing)
    }

    @ViewBuilder
    private func row(_ lbl: String, _ val: String, multiline: Bool = false,
                     color: Color = .primary) -> some View {
        HStack(alignment: multiline ? .top : .center) {
            label(lbl)
            Text(val).font(.caption).foregroundStyle(color)
                .lineLimit(multiline ? nil : 1).textSelection(.enabled)
        }
    }

    private func defaultAppName(for entry: SidecarEntry) -> String {
        guard let urlStr = entry.effectiveUrl, let url = URL(string: urlStr) else { return "Preview" }
        if entry.assetType == .pdf { return "Preview" }
        if let app = NSWorkspace.shared.urlForApplication(toOpen: url) {
            return app.deletingPathExtension().lastPathComponent
        }
        return "Default App"
    }
}
