import Foundation
import AppKit
import WebKit
import MCSRTrackerCore

@MainActor
final class AssetCache: ObservableObject {

    @Published var cachedURLs: [String: URL] = [:]  // entry.id → local file URL
    @Published var inFlight: Set<String>     = []

    private let cacheDir: URL
    private let session: URLSession

    init(cacheDir: URL) {
        self.cacheDir = cacheDir
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 30
        session = URLSession(configuration: cfg)
    }

    func localURL(for entry: SidecarEntry) -> URL? { cachedURLs[entry.id] }

    func fetch(_ entry: SidecarEntry) {
        guard !inFlight.contains(entry.id),
              cachedURLs[entry.id] == nil,
              let urlStr = entry.effectiveUrl,
              let url = URL(string: urlStr) else { return }
        inFlight.insert(entry.id)
        if entry.assetType == .pdf {
            downloadFile(entry: entry, from: url)
        } else {
            takeWebScreenshot(entry: entry, url: url)
        }
    }

    // MARK: - PDF Download

    private func downloadFile(entry: SidecarEntry, from url: URL) {
        let dest = cacheDir.appendingPathComponent("\(entry.id).pdf")
        if FileManager.default.fileExists(atPath: dest.path) {
            cachedURLs[entry.id] = dest; inFlight.remove(entry.id); return
        }
        Task {
            do {
                let (tmp, _) = try await session.download(from: url)
                try? FileManager.default.removeItem(at: dest)
                try FileManager.default.moveItem(at: tmp, to: dest)
                await MainActor.run { self.cachedURLs[entry.id] = dest; self.inFlight.remove(entry.id) }
            } catch {
                await MainActor.run { self.inFlight.remove(entry.id) }
            }
        }
    }

    // MARK: - Web Screenshot

    private func takeWebScreenshot(entry: SidecarEntry, url: URL) {
        let dest = cacheDir.appendingPathComponent("\(entry.id).png")
        if FileManager.default.fileExists(atPath: dest.path) {
            cachedURLs[entry.id] = dest; inFlight.remove(entry.id); return
        }
        let screenshotter = WebScreenshotter()
        screenshotter.capture(url: url) { [weak self] image in
            guard let self, let img = image, let png = img.pngData() else {
                Task { @MainActor in self?.inFlight.remove(entry.id) }
                return
            }
            try? png.write(to: dest)
            Task { @MainActor in
                self.cachedURLs[entry.id] = dest
                self.inFlight.remove(entry.id)
            }
        }
    }
}

// MARK: - Web Screenshotter

final class WebScreenshotter: NSObject, WKNavigationDelegate {
    private var webView: WKWebView?
    private var completion: ((NSImage?) -> Void)?
    private var timer: Timer?

    func capture(url: URL, completion: @escaping (NSImage?) -> Void) {
        self.completion = completion
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .nonPersistent()
        let wv = WKWebView(frame: CGRect(x: 0, y: 0, width: 1280, height: 800), configuration: cfg)
        wv.navigationDelegate = self
        self.webView = wv
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: false) { [weak self] _ in
            self?.snapshot()
        }
        wv.load(URLRequest(url: url))
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.snapshot() }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        finish(nil)
    }

    private func snapshot() {
        timer?.invalidate(); timer = nil
        guard let wv = webView else { finish(nil); return }
        let cfg = WKSnapshotConfiguration()
        cfg.rect = CGRect(x: 0, y: 0, width: 1280, height: 800)
        wv.takeSnapshot(with: cfg) { [weak self] image, _ in self?.finish(image) }
    }

    private func finish(_ image: NSImage?) {
        webView?.navigationDelegate = nil; webView = nil
        completion?(image); completion = nil
    }
}

// MARK: - NSImage → PNG data

extension NSImage {
    func pngData() -> Data? {
        guard let tiff   = tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff) else { return nil }
        return bitmap.representation(using: .png, properties: [:])
    }
}
