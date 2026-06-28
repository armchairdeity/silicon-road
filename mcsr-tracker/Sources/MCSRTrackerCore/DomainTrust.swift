import Foundation

enum DomainTrust {

    static let trusted: Set<String> = [
        // Distributors
        "mouser.com", "digikey.com", "digi-key.com", "arrow.com",
        "avnet.com", "newark.com", "jameco.com", "adafruit.com",
        "sparkfun.com", "lcsc.com", "farnell.com", "element14.com",
        // Manufacturers
        "ti.com", "st.com", "stmicroelectronics.com", "nxp.com",
        "microchip.com", "analog.com", "maxim-ic.com", "maximintegrated.com",
        "rohm.com", "renesas.com", "infineon.com", "onsemi.com",
        "vishay.com", "bourns.com", "murata.com", "tdk.com",
        "panasonic.com", "yageo.com", "samsung.com", "epson.com",
        "atmel.com", "cypress.com", "xilinx.com", "altera.com",
        "latticesemi.com", "idt.com", "skyworksinc.com",
        // Data aggregators
        "datasheetspdf.com", "alldatasheet.com", "datasheet4u.com",
        "octopart.com", "findchips.com",
    ]

    enum Status {
        case trusted, unverified, noURL

        var label: String {
            switch self {
            case .trusted:    return "✓ Trusted source"
            case .unverified: return "⚠ Unverified domain"
            case .noURL:      return "— No URL"
            }
        }
    }

    static func check(urlString: String?) -> Status {
        guard let str = urlString, !str.isEmpty,
              let host = URL(string: str)?.host?.lowercased() else { return .noURL }
        let parts = host.split(separator: ".")
        for i in 0 ..< parts.count - 1 {
            let candidate = parts[i...].joined(separator: ".")
            if trusted.contains(candidate) { return .trusted }
        }
        return .unverified
    }
}
