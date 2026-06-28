import XCTest
@testable import MCSRTrackerCore

final class DomainTrustTests: XCTestCase {

    func testTrustedManufacturer() {
        XCTAssertEqual(DomainTrust.check(urlString: "https://www.ti.com/lit/ds/symlink/cd4069ub.pdf"), .trusted)
    }

    func testTrustedSubdomain() {
        XCTAssertEqual(DomainTrust.check(urlString: "https://datasheet.lcsc.com/lcsc/2109251830_Texas-Instruments_LM358DR_C7950.pdf"), .trusted)
    }

    func testTrustedDistributor() {
        XCTAssertEqual(DomainTrust.check(urlString: "https://www.mouser.com/datasheet/2/405/LM358-1519.pdf"), .trusted)
    }

    func testUnverifiedUnknownSite() {
        XCTAssertEqual(DomainTrust.check(urlString: "https://some-sketchy-mirror.ru/datasheets/lm358.pdf"), .unverified)
    }

    func testNoURLReturnsNoURL() {
        XCTAssertEqual(DomainTrust.check(urlString: nil), .noURL)
        XCTAssertEqual(DomainTrust.check(urlString: ""), .noURL)
    }

    func testMalformedURLReturnsNoURL() {
        XCTAssertEqual(DomainTrust.check(urlString: "not a url at all"), .noURL)
    }

    func testDigiKeyTrusted() {
        XCTAssertEqual(DomainTrust.check(urlString: "https://media.digikey.com/pdf/data-sheets/ti-pdf/lm358.pdf"), .trusted)
    }
}
