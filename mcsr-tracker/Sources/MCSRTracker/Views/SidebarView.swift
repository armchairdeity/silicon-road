import SwiftUI

struct SidebarView: View {
    let entries:    [SidecarEntry]
    @Binding var selectedID:  String?
    @Binding var selectedIDs: Set<String>
    @Binding var filter:      SidebarFilter
    let store: SidecarStore

    var body: some View {
        VStack(spacing: 0) {
            // Filter picker
            Picker("Filter", selection: $filter) {
                ForEach(SidebarFilter.allCases) { f in
                    Text(f.rawValue).tag(f)
                }
            }
            .pickerStyle(.menu)
            .padding(.horizontal, 8).padding(.vertical, 6)

            Divider()

            // Thumbnail list
            if entries.isEmpty {
                Spacer()
                Text("No items").foregroundStyle(.secondary).font(.caption)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(entries) { entry in
                            ThumbnailItemView(
                                entry:      entry,
                                isSelected: selectedID == entry.id,
                                isChecked:  selectedIDs.contains(entry.id),
                                onSelect:   { selectedID = entry.id },
                                onToggle: {
                                    if selectedIDs.contains(entry.id) {
                                        selectedIDs.remove(entry.id)
                                    } else {
                                        selectedIDs.insert(entry.id)
                                    }
                                }
                            )
                            Divider()
                        }
                    }
                }
            }

            Divider()

            // Bulk action bar
            BulkActionBar(selectedIDs: $selectedIDs, store: store)
        }
    }
}

// MARK: - Bulk Action Bar

struct BulkActionBar: View {
    @Binding var selectedIDs: Set<String>
    let store: SidecarStore
    private var enabled: Bool { selectedIDs.count >= 2 }

    var body: some View {
        HStack(spacing: 8) {
            if enabled {
                Text("\(selectedIDs.count) selected")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            Button("👍🏼") { store.accept(ids: selectedIDs); selectedIDs = [] }
                .disabled(!enabled).help("Accept selected")
            Button("👎🏼") { store.reject(ids: selectedIDs); selectedIDs = [] }
                .disabled(!enabled).help("Reject selected")
            Button("🚮") { store.delete(ids: selectedIDs); selectedIDs = [] }
                .disabled(!enabled).help("Delete selected — no undo")
        }
        .padding(.horizontal, 8).padding(.vertical, 8)
        .background(.bar)
    }
}
