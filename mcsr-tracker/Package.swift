// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MCSRTracker",
    platforms: [.macOS(.v13)],
    targets: [
        // Pure-Swift core: models and domain logic — no AppKit/SwiftUI dependency.
        // Testable by the test target below.
        .target(
            name: "MCSRTrackerCore",
            path: "Sources/MCSRTrackerCore"
        ),

        // Main app: SwiftUI views, AppKit glue, WebKit screenshotter.
        .executableTarget(
            name: "MCSRTracker",
            dependencies: ["MCSRTrackerCore"],
            path: "Sources/MCSRTracker",
            linkerSettings: [
                .linkedFramework("QuickLookUI"),
                .linkedFramework("WebKit"),
            ]
        ),

        // Unit tests for the core layer.
        .testTarget(
            name: "MCSRTrackerTests",
            dependencies: ["MCSRTrackerCore"],
            path: "Tests/MCSRTrackerTests"
        )
    ]
)
