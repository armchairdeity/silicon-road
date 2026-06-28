import SwiftUI

struct MenuBarContent: View {
    @EnvironmentObject var store: SidecarStore
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Title
            HStack {
                Image(systemName: "cpu").foregroundStyle(.orange)
                Text("MCSR Tracker").font(.headline)
                Spacer()
            }
            .padding(.horizontal, 12).padding(.vertical, 8)

            Divider()

            // Primary action
            if store.pendingCount > 0 {
                Button {
                    openWindow(id: "curation-panel")
                    NSApp.activate(ignoringOtherApps: true)
                } label: {
                    HStack {
                        Image(systemName: "tray.and.arrow.down").foregroundStyle(.orange)
                        Text("Curate Now")
                        Spacer()
                        Text("\(store.pendingCount) pending")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 12).padding(.vertical, 6)
            } else {
                Label("Queue empty — nothing to curate", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12).padding(.vertical, 6)
            }

            Divider()

            // Stats
            statRow("Accepted",    count: store.entries.filter { $0.curationStatus == .accepted }.count, color: .green)
            statRow("Rejected",    count: store.entries.filter { $0.curationStatus == .rejected }.count, color: .red)
            statRow("Pending",     count: store.pendingCount, color: .orange)
            statRow("Not Vectored", count: store.entries.filter { $0.isPendingVectorization }.count, color: .purple)

            Divider()

            Button("Refresh")             { store.load() }.keyboardShortcut("r")
                .padding(.horizontal, 12).padding(.vertical, 4)
            Button("Quit MCSR Tracker")   { NSApp.terminate(nil) }.keyboardShortcut("q")
                .padding(.horizontal, 12).padding(.vertical, 4)
        }
        .frame(width: 260)
    }

    private func statRow(_ label: String, count: Int, color: Color) -> some View {
        HStack {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label).font(.caption)
            Spacer()
            Text("\(count)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12).padding(.vertical, 2)
    }
}
