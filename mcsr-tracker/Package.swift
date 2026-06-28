// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MCSRTracker",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "MCSRTracker",
            path: "Sources/MCSRTracker",
            linkerSettings: [
                .linkedFramework("QuickLookUI"),
                .linkedFramework("WebKit"),
            ]
        )
    ]
)
