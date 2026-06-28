import XCTest
@testable import MCSRTrackerCore

final class SidecarEntryTests: XCTestCase {

    // MARK: - JSON decoding

    /// Mirrors a real entry from chase_results.json (CD4069UBPW)
    private let realEntryJSON = """
    {
      "doc_id": "ics_cd4069ubpw",
      "part_number": "CD4069UBPW",
      "manufacturer": "Texas Instruments",
      "datasheet_url": "https://www.ti.com/lit/gpn/CD4069UB",
      "technical_summary": "A CMOS hex inverter.",
      "key_specs": ["Operating Voltage: 3-18V"],
      "applications": ["Logic inversion"],
      "raw_response": "DATASHEET_URL: ...",
      "datasheet_url_valid": true,
      "datasheet_content_type": "application/pdf",
      "error": null,
      "skipped": false,
      "skip_reason": null,
      "url_validation": {
        "url": "https://www.ti.com/lit/gpn/CD4069UB",
        "reachable": true,
        "status_code": 200,
        "content_type": "application/pdf",
        "final_url": "https://www.ti.com/lit/ds/symlink/cd4069ub.pdf",
        "is_pdf": true,
        "error": null
      },
      "curated": "accepted"
    }
    """.data(using: .utf8)!

    private var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }

    func testDecodesRealEntry() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertEqual(entry.id,           "ics_cd4069ubpw")
        XCTAssertEqual(entry.partNumber,   "CD4069UBPW")
        XCTAssertEqual(entry.manufacturer, "Texas Instruments")
        XCTAssertEqual(entry.datasheetUrlValid, true)
        XCTAssertEqual(entry.datasheetContentType, "application/pdf")
        XCTAssertEqual(entry.curated, "accepted")
    }

    func testCurationStatusAccepted() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertEqual(entry.curationStatus, .accepted)
    }

    func testCurationStatusNullIsPending() throws {
        var json = realEntryJSON
        // Replace "accepted" with null
        var raw = try JSONSerialization.jsonObject(with: json) as! [String: Any]
        raw["curated"] = NSNull()
        json = try JSONSerialization.data(withJSONObject: raw)
        let entry = try decoder.decode(SidecarEntry.self, from: json)
        XCTAssertEqual(entry.curationStatus, .pending)
    }

    func testAssetTypeFromContentType() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertEqual(entry.assetType, .pdf)
    }

    func testAssetTypeWebpageWhenHTMLContentType() throws {
        var raw = try JSONSerialization.jsonObject(with: realEntryJSON) as! [String: Any]
        raw["datasheet_content_type"] = "text/html"
        if var validation = raw["url_validation"] as? [String: Any] {
            validation["content_type"] = "text/html"
            validation["is_pdf"] = false
            raw["url_validation"] = validation
        }
        let json = try JSONSerialization.data(withJSONObject: raw)
        let entry = try decoder.decode(SidecarEntry.self, from: json)
        XCTAssertEqual(entry.assetType, .webpage)
    }

    func testEffectiveURLPrefersValidationFinalURL() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertEqual(entry.effectiveUrl,
                       "https://www.ti.com/lit/ds/symlink/cd4069ub.pdf")
    }

    func testIsPendingVectorizationWhenAcceptedAndNotVectored() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        // curated=accepted, vectored_at absent → pending vectorization
        XCTAssertTrue(entry.isPendingVectorization)
    }

    func testURLValidationDecodes() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertEqual(entry.urlValidation?.isPdf, true)
        XCTAssertEqual(entry.urlValidation?.statusCode, 200)
    }

    // MARK: - SidebarFilter matching

    func testFilterAll() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertTrue(entry.matches(filter: .all))
    }

    func testFilterPendingExcludesAccepted() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertFalse(entry.matches(filter: .pending))
    }

    func testFilterAcceptedMatchesAccepted() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertTrue(entry.matches(filter: .accepted))
    }

    func testFilterNotVectoredMatchesAcceptedWithoutDate() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertTrue(entry.matches(filter: .notVectored))
    }

    func testFilterPDFMatchesPDFAsset() throws {
        let entry = try decoder.decode(SidecarEntry.self, from: realEntryJSON)
        XCTAssertTrue(entry.matches(filter: .pdf))
        XCTAssertFalse(entry.matches(filter: .webpage))
    }
}
