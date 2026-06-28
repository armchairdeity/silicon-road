import Foundation

// MARK: - Enums

public enum CurationStatus: String {
    case accepted, rejected, pending
}

public enum AssetType: String, CaseIterable, Identifiable {
    case pdf     = "PDF"
    case webpage = "Web Page"
    case unknown = "Unknown"
    public var id: String { rawValue }
}

public enum SidebarFilter: String, CaseIterable, Identifiable {
    case all        = "All"
    case pending    = "Pending"
    case curated    = "Curated"
    case accepted   = "Accepted"
    case notVectored = "Accepted / Not Vectored"
    case pdf        = "PDF"
    case webpage    = "Web Page"
    public var id: String { rawValue }
}

// MARK: - URL Validation

public struct UrlValidation: Codable {
    public var url: String?
    public var reachable: Bool?
    public var statusCode: Int?
    public var contentType: String?
    public var finalUrl: String?
    public var isPdf: Bool?
    public var error: String?

    enum CodingKeys: String, CodingKey {
        case url, reachable, error
        case statusCode  = "status_code"
        case contentType = "content_type"
        case finalUrl    = "final_url"
        case isPdf       = "is_pdf"
    }
}

// MARK: - Main Model

public struct SidecarEntry: Codable, Identifiable, Hashable {
    public var id: String
    public var partNumber: String?
    public var manufacturer: String?
    public var datasheetUrl: String?
    public var datasheetUrlValid: Bool?
    public var datasheetContentType: String?
    public var technicalSummary: String?
    public var keySpecs: [String]?
    public var applications: [String]?
    public var rawResponse: String?
    public var error: String?
    public var skipped: Bool?
    public var skipReason: String?
    public var urlValidation: UrlValidation?
    public var curated: String?        // "accepted", "rejected", or nil
    public var rejectedAt: Date?
    public var vectoredAt: Date?

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

    public var curationStatus: CurationStatus {
        guard let c = curated else { return .pending }
        return CurationStatus(rawValue: c) ?? .pending
    }

    public var assetType: AssetType {
        let ct = datasheetContentType ?? urlValidation?.contentType ?? ""
        if ct.contains("pdf") { return .pdf }
        if ct.contains("html") || ct.contains("text/") { return .webpage }
        let url = (urlValidation?.finalUrl ?? datasheetUrl ?? "").lowercased()
        if url.hasSuffix(".pdf") { return .pdf }
        if url.isEmpty { return .unknown }
        return .webpage
    }

    public var effectiveUrl: String? { urlValidation?.finalUrl ?? datasheetUrl }

    public var isPendingVectorization: Bool {
        curationStatus == .accepted && vectoredAt == nil
    }

    public func matches(filter: SidebarFilter) -> Bool {
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

    public static func == (lhs: SidecarEntry, rhs: SidecarEntry) -> Bool { lhs.id == rhs.id }
    public func hash(into hasher: inout Hasher) { hasher.combine(id) }
}
