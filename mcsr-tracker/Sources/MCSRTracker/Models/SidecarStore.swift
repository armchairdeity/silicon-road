import Foundation
import Combine

final class SidecarStore: ObservableObject {

    // MARK: - Published State
    @Published var entries: [SidecarEntry] = []
    @Published var pendingCount: Int = 0
    @Published var loadError: String?

    // MARK: - Paths
    static let sidecarDir = URL(fileURLWithPath: NSHomeDirectory())
        .appendingPathComponent(".silicon_road")
    static let sidecarURL = sidecarDir.appendingPathComponent("chase_results.json")
    static let cacheDir   = sidecarDir.appendingPathComponent("cache")

    // MARK: - Private
    private var directorySource: DispatchSourceFileSystemObject?
    private let ioQueue = DispatchQueue(label: "com.mcsr.sidecarIO", qos: .utility)

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    // MARK: - Init / Deinit
    init() {
        createCacheDirIfNeeded()
        load()
        startWatching()
    }

    deinit { directorySource?.cancel() }

    // MARK: - Load

    func load() {
        ioQueue.async { [weak self] in
            guard let self else { return }
            guard FileManager.default.fileExists(atPath: Self.sidecarURL.path) else {
                DispatchQueue.main.async { self.entries = []; self.pendingCount = 0 }
                return
            }
            do {
                let data = try Data(contentsOf: Self.sidecarURL)
                let raw  = try Self.decoder.decode([String: SidecarEntry].self, from: data)
                let sorted  = raw.values.sorted { ($0.partNumber ?? "") < ($1.partNumber ?? "") }
                let pending = sorted.filter { $0.curationStatus == .pending }.count
                DispatchQueue.main.async {
                    self.entries      = sorted
                    self.pendingCount = pending
                    self.loadError    = nil
                }
            } catch {
                DispatchQueue.main.async {
                    self.loadError = error.localizedDescription
                }
            }
        }
    }

    // MARK: - Save

    private func save() {
        let dict = Dictionary(uniqueKeysWithValues: entries.map { ($0.id, $0) })
        ioQueue.async { [weak self] in
            guard let self else { return }
            do {
                let data = try Self.encoder.encode(dict)
                let tmp  = Self.sidecarURL.deletingLastPathComponent()
                    .appendingPathComponent("chase_results.json.tmp")
                try data.write(to: tmp, options: .atomic)
                _ = try FileManager.default.replaceItemAt(Self.sidecarURL, withItemAt: tmp)
            } catch {
                DispatchQueue.main.async {
                    self.loadError = "Save failed: \(error.localizedDescription)"
                }
            }
        }
    }

    // MARK: - Actions

    func accept(ids: Set<String>) {
        for i in entries.indices where ids.contains(entries[i].id) {
            entries[i].curated    = "accepted"
            entries[i].rejectedAt = nil
        }
        refreshPendingCount(); save()
    }

    func reject(ids: Set<String>) {
        let now = Date()
        for i in entries.indices where ids.contains(entries[i].id) {
            entries[i].curated    = "rejected"
            entries[i].rejectedAt = now
        }
        refreshPendingCount(); save()
    }

    func keep(ids: Set<String>) {
        for i in entries.indices where ids.contains(entries[i].id) {
            entries[i].curated    = nil
            entries[i].rejectedAt = nil
        }
        refreshPendingCount(); save()
    }

    func delete(ids: Set<String>) {
        entries.removeAll { ids.contains($0.id) }
        refreshPendingCount(); save()
    }

    // MARK: - Helpers

    private func refreshPendingCount() {
        pendingCount = entries.filter { $0.curationStatus == .pending }.count
    }

    private func createCacheDirIfNeeded() {
        try? FileManager.default.createDirectory(
            at: Self.cacheDir, withIntermediateDirectories: true)
    }

    // MARK: - File Watching (watch directory — sidecar is atomically replaced)

    private func startWatching() {
        let fd = open(Self.sidecarDir.path, O_EVTONLY)
        guard fd >= 0 else { return }
        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd, eventMask: .write, queue: ioQueue)
        source.setEventHandler { [weak self] in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self?.load() }
        }
        source.setCancelHandler { close(fd) }
        source.resume()
        directorySource = source
    }
}
