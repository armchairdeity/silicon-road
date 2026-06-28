import Foundation

// MARK: - Enums

enum CurationStatus: String {
    case accepted, rejected, pending
}

enum AssetType: String, CaseIterable, Identifiable {
    case pdf     = "PDF"
    case webpage = "Web Page"
    case unknown = "Unknown"
    var id: String { rawValue }
}

enum SidebarFilter: String, CaseIterable, Identifiable {
    case all        = "All"
    case pending    = "Pending"
    case curated    = "Curated"
    case accepted   = "Accepted"
    case notVectored = "Accepted / Not Vectored"
    case pdf        = "PDF"
    case webpage    = "Web Page"
    var id: String { rawValue }
}

// MARK: - URL Validation

struct UrlValidation: Codable {
    var url: String?
    var reachable: Bool?
    var statusCode: Int?
    var contentType: String?
    var finalUrl: String?
    var isPdf: Bool?
    var error: String?

    enum CodingKeys: String, CodingKey {
        case url, reachable, error
        case statusCode  = "status_code"
        case contentType = "content_type"
        case finalUrl    = "final_url"
        case isPdf       = "is_pdf"
    }
}

// MARK: - Main Model

struct SidecarEntry: Codable, Identifiable, Hashable {
    var id: String
    var partNumber: String?
    var manufacturer: String?
    var datasheetUrl: String?
    var datasheetUrlValid: Bool?
    var datasheetContentType: String?
    var technicalSummary: String?
    var keySpecs: [String]?
    var applications: [String]?
    var rawResponse: String?
    var error: String?
    var skipped: Bool?
    var skipReason: String?
    var urlValidation: UrlValidation?
    var curated: String?        // "accepted", "rejected", or nil
    var rejectedAt: Date?
    var vectoredAt: Date?

    enum CodingKeys: String, CodingKey {
        case id                   = "doc_id"
        case partNumber           = "part_number"
        case manufacturer
        case datasheetUrl         = "datasheet_url"
        case datasheetUrlValid    = "datasheet_url_valid"
        case datasheetContentType = "datasheet_content_type"
        case technicalSummary     = "technical_summary"
        case keySpecs             = "key_specs"
        case applications
        case rawResponse          = "raw_response"
        case error, skipped
        case skipReason           = "skip_reason"
        case urlValidation        = "url_validation"
        case curated
        case rejectedAt           = "rejected_at"
        case vectoredAt           = "vectored_at"
    }

    // MARK: - Computed Properties

    var curationStatus: CurationStatus {
        guard let c = curated else { return .pending }
        return CurationStatus(rawValue: c) ?? .pending
    }

    var assetType: AssetType {
        let ct = datasheetContentType ?? urlValidation?.contentType ?? ""
        if ct.contains("pdf") { return .pdf }
        if ct.contains("html") || ct.contains("text/") { return .webpage }
        let url = (urlValidation?.finalUrl ?? datasheetUrl ?? "").lowercased()
        if url.hasSuffix(".pdf") { return .pdf }
        if url.isEmpty { return .unknown }
        return .webpage
    }

    var effectiveUrl: String? { urlValidation?.finalUrl ?? datasheetUrl }

    var isPendingVectorization: Bool {
        curationStatus == .accepted && vectoredAt == nil
    }

    func matches(filter: SidebarFilter) -> Bool {
        switch filter {
        case .all:        return true
        case .pending:    return curationStatus == .pending
        case .curated:    return curationStatus != .pending
        case .accepted:   return curationStatus == .accepted
        case .notVectored: return isPendingVectorization
        case .pdf:        return assetType == .pdf
        case .webpage:    return assetType == .webpage
        }
    }

    static func == (lhs: SidecarEntry, rhs: SidecarEntry) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}
