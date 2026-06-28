import SwiftUI

struct CurationPanelView: View {
    @EnvironmentObject var store: SidecarStore
    @EnvironmentObject var cache: AssetCache

    @State private var selectedID:  String?
    @State private var selectedIDs: Set<String> = []
    @State private var filter: SidebarFilter = .pending

    private var filtered: [SidecarEntry] {
        store.entries.filter { $0.matches(filter: filter) }
    }

    private var selected: SidecarEntry? {
        guard let id = selectedID else { return nil }
        return store.entries.first { $0.id == id }
    }

    var body: some View {
        HSplitView {
            SidebarView(
                entries: filtered,
                selectedID:  $selectedID,
                selectedIDs: $selectedIDs,
                filter:      $filter,
                store:       store
            )
            .frame(minWidth: 220, maxWidth: 320)

            Group {
                if let entry = selected {
                    DetailView(entry: entry, store: store, cache: cache)
                } else {
                    EmptySelectionView(count: filtered.count)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .onChange(of: filtered) { newList in
            if let id = selectedID, !newList.contains(where: { $0.id == id }) {
                selectedID = newList.first?.id
            } else if selectedID == nil {
                selectedID = newList.first?.id
            }
        }
    }
}

struct EmptySelectionView: View {
    let count: Int
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: count == 0 ? "tray" : "arrow.left")
                .font(.system(size: 48)).foregroundStyle(.tertiary)
            Text(count == 0 ? "No items match this filter" : "Select an item to preview")
                .font(.title3).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
