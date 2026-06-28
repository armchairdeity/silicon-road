import SwiftUI
import QuickLookUI
import AppKit
import MCSRTrackerCore

struct PreviewView: View {
    let entry: SidecarEntry
    @ObservedObject var cache: AssetCache

    var body: some View {
        ZStack {
            Color(nsColor: .controlBackgroundColor)

            if cache.inFlight.contains(entry.id) {
                ProgressView("Loading preview…")

            } else if let localURL = cache.localURL(for: entry) {
                if entry.assetType == .webpage {
                    if let img = NSImage(contentsOf: localURL) {
                        Image(nsImage: img)
                            .resizable()
                            .scaledToFit()
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        placeholder("Screenshot unavailable", icon: "photo.slash")
                    }
                } else {
                    QuickLookPreviewView(url: localURL)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }

            } else if entry.effectiveUrl != nil {
                VStack(spacing: 12) {
                    Image(systemName: "arrow.down.circle")
                        .font(.system(size: 36)).foregroundStyle(.secondary)
                    Text("Preview not yet loaded").foregroundStyle(.secondary)
                    Button("Load") { cache.fetch(entry) }.buttonStyle(.borderedProminent)
                }

            } else {
                placeholder("No asset URL", icon: "doc.questionmark")
            }
        }
        .onAppear { cache.fetch(entry) }
        .onChange(of: entry.id) { _ in cache.fetch(entry) }
    }

    private func placeholder(_ msg: String, icon: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: icon).font(.system(size: 36)).foregroundStyle(.secondary)
            Text(msg).foregroundStyle(.secondary)
        }
    }
}

// MARK: - QLPreviewView wrapper

struct QuickLookPreviewView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> QLPreviewView {
        let v = QLPreviewView(frame: .zero, style: .normal)!
        v.autostarts = true
        return v
    }

    func updateNSView(_ v: QLPreviewView, context: Context) {
        v.previewItem = url as QLPreviewItem
    }
}
