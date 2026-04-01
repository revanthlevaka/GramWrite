import Foundation

#if canImport(FoundationModels)
import FoundationModels

private let foundationModelIdentifier = "apple.foundation"

private struct StatusResponse: Encodable {
    let supported: Bool
    let available: Bool
    let reason: String?
    let model: String
}

private struct CorrectionRequest: Decodable {
    let text: String
    let instructions: String
}

private struct CorrectionResponse: Encodable {
    let ok: Bool
    let hasCorrection: Bool
    let correction: String
    let error: String?
}

@available(macOS 26.0, *)
@main
private struct GramWriteFoundationModelsCLI {
    static func main() async {
        let command = CommandLine.arguments.dropFirst().first ?? "status"
        do {
            switch command {
            case "status":
                try writeJSON(status())
            case "correct":
                let request = try readRequest()
                try await writeJSON(correct(request))
            default:
                try writeJSON(
                    CorrectionResponse(
                        ok: false,
                        hasCorrection: false,
                        correction: "",
                        error: "Unknown command: \(command)"
                    )
                )
                Foundation.exit(EXIT_FAILURE)
            }
        } catch {
            let response = CorrectionResponse(
                ok: false,
                hasCorrection: false,
                correction: "",
                error: String(describing: error)
            )
            try? writeJSON(response)
            Foundation.exit(EXIT_FAILURE)
        }
    }

    private static func status() -> StatusResponse {
        let model = SystemLanguageModel.default
        switch model.availability {
        case .available:
            return StatusResponse(
                supported: true,
                available: true,
                reason: nil,
                model: foundationModelIdentifier
            )
        case .unavailable(let reason):
            return StatusResponse(
                supported: true,
                available: false,
                reason: String(describing: reason),
                model: foundationModelIdentifier
            )
        @unknown default:
            return StatusResponse(
                supported: true,
                available: false,
                reason: "unknown_unavailable_reason",
                model: foundationModelIdentifier
            )
        }
    }

    private static func correct(_ request: CorrectionRequest) async throws -> CorrectionResponse {
        let availability = status()
        guard availability.available else {
            return CorrectionResponse(
                ok: false,
                hasCorrection: false,
                correction: "",
                error: availability.reason ?? "Apple Foundation Models are unavailable."
            )
        }

        let session = LanguageModelSession(
            instructions: request.instructions
        )
        let prompt = """
        Correct grammar and spelling only in the same language.
        Do not translate.
        Do not rewrite for style.
        Do not change intentional screenplay fragments unless they are true grammar or spelling mistakes.
        If the text has no correction, respond with exactly: NO_CORRECTION
        If the text needs correction, respond with only the corrected text and nothing else.

        Source text:
        \(request.text)
        """

        let response = try await session.respond(to: prompt)
        let content = response.content.trimmingCharacters(in: .whitespacesAndNewlines)
        let hasCorrection = !content.isEmpty && content.uppercased() != "NO_CORRECTION"
        return CorrectionResponse(
            ok: true,
            hasCorrection: hasCorrection,
            correction: hasCorrection ? content : "",
            error: nil
        )
    }

    private static func readRequest() throws -> CorrectionRequest {
        let data = FileHandle.standardInput.readDataToEndOfFile()
        return try JSONDecoder().decode(CorrectionRequest.self, from: data)
    }

    private static func writeJSON<T: Encodable>(_ value: T) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        let data = try encoder.encode(value)
        FileHandle.standardOutput.write(data)
    }
}

#else

private struct StatusResponse: Encodable {
    let supported: Bool
    let available: Bool
    let reason: String?
    let model: String
}

@main
private struct GramWriteFoundationModelsUnavailableCLI {
    static func main() {
        let response = StatusResponse(
            supported: false,
            available: false,
            reason: "FoundationModels framework is not available in the active Apple SDK.",
            model: "apple.foundation"
        )

        let encoder = JSONEncoder()
        if let data = try? encoder.encode(response) {
            FileHandle.standardOutput.write(data)
        }
    }
}

#endif
