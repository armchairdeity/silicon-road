import Foundation
import AppKit

/// Manages the launchd login item for MCSR Tracker.
/// On first launch, asks the user once via NSAlert.
/// Uses a LaunchAgents plist since we are an SPM executable, not a bundled app.
enum LoginItemManager {

    private static let plistLabel  = "com.mcsr.tracker"
    private static let plistName   = "com.mcsr.tracker.plist"
    private static let askedKey    = "askedAboutLoginItem"

    private static var plistURL: URL {
        let launchAgents = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents")
        return launchAgents.appendingPathComponent(plistName)
    }

    // MARK: - Public

    /// Call once from app startup. Shows the prompt only on first run.
    static func promptIfNeeded() {
        guard !UserDefaults.standard.bool(forKey: askedKey) else { return }
        UserDefaults.standard.set(true, forKey: askedKey)

        // NSAlert must run on the main thread
        DispatchQueue.main.async { showAlert() }
    }

    static func isEnabled() -> Bool {
        FileManager.default.fileExists(atPath: plistURL.path)
    }

    static func enable() {
        guard let execPath = executablePath() else { return }
        let plist: [String: Any] = [
            "Label":             plistLabel,
            "ProgramArguments":  [execPath],
            "RunAtLoad":         true,
            "KeepAlive":         false,
            "StandardOutPath":   "\(NSHomeDirectory())/.silicon_road/mcsr-tracker.log",
            "StandardErrorPath": "\(NSHomeDirectory())/.silicon_road/mcsr-tracker.log",
        ]
        try? FileManager.default.createDirectory(
            at: plistURL.deletingLastPathComponent(),
            withIntermediateDirectories: true)
        if let data = try? PropertyListSerialization.data(
            fromPropertyList: plist, format: .xml, options: 0) {
            try? data.write(to: plistURL, options: .atomic)
        }
        bootstrap()
    }

    static func disable() {
        bootout()
        try? FileManager.default.removeItem(at: plistURL)
    }

    // MARK: - Private

    private static func showAlert() {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText     = "Start MCSR Tracker at Login?"
        alert.informativeText = "Would you like MCSR Tracker to launch automatically each time you log in?"
        alert.alertStyle      = .informational
        alert.icon            = NSImage(systemSymbolName: "cpu", accessibilityDescription: nil)
        alert.addButton(withTitle: "Yes, start at login")
        alert.addButton(withTitle: "Not now")

        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            enable()
        }
    }

    private static func executablePath() -> String? {
        // Prefer the resolved symlink so the plist survives swift build rebuilds
        let raw = CommandLine.arguments[0]
        return (try? URL(fileURLWithPath: raw).resolvingSymlinksInPath().path) ?? raw
    }

    private static func bootstrap() {
        let uid  = getuid()
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        proc.arguments     = ["bootstrap", "gui/\(uid)", plistURL.path]
        try? proc.run()
        proc.waitUntilExit()
    }

    private static func bootout() {
        let uid  = getuid()
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        proc.arguments     = ["bootout", "gui/\(uid)/\(plistLabel)"]
        try? proc.run()
        proc.waitUntilExit()
    }
}
