import SwiftUI
import MCSRTrackerCore

@main
struct MCSRTrackerApp: App {
    @StateObject private var store = SidecarStore()
    @StateObject private var cache = AssetCache(cacheDir: SidecarStore.cacheDir)

    var body: some Scene {
        MenuBarExtra {
            MenuBarContent()
                .environmentObject(store)
        } label: {
            MenuBarLabel(count: store.pendingCount)
        }
        .menuBarExtraStyle(.menu)

        Window("MCSR Tracker", id: "curation-panel") {
            CurationPanelView()
                .environmentObject(store)
                .environmentObject(cache)
                .frame(minWidth: 960, minHeight: 640)
        }
        .windowResizability(.contentSize)
        .defaultSize(width: 1140, height: 740)
    }
}

// MARK: - Menu Bar Label

struct MenuBarLabel: View {
    let count: Int
    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: count > 0 ? "cpu.fill" : "cpu")
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(count > 0 ? Color.orange : Color.primary)
            if count > 0 {
                Text("\(count)")
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(Color.orange)
            }
        }
    }
}
