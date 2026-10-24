import Foundation
import FoundationModels

private let protocolPrefix = "CLONE_VOICE_APPLE_FM:"

private func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
          let text = String(data: data, encoding: .utf8) else { return }
    print(protocolPrefix + text)
}

@available(macOS 26.0, *)
private func unavailableReason(_ reason: SystemLanguageModel.Availability.UnavailableReason) -> String {
    switch reason {
    case .appleIntelligenceNotEnabled: return "apple_intelligence_not_enabled"
    case .deviceNotEligible: return "device_not_eligible"
    case .modelNotReady: return "model_not_ready"
    @unknown default: return "model_unavailable"
    }
}

@available(macOS 26.0, *)
private func generationReason(_ error: Error) -> String {
    guard let error = error as? LanguageModelSession.GenerationError else { return "generation_failed" }
    switch error {
    case .exceededContextWindowSize: return "context_window_exceeded"
    case .assetsUnavailable: return "model_not_ready"
    case .guardrailViolation, .refusal: return "content_refused"
    case .unsupportedLanguageOrLocale: return "unsupported_language"
    case .decodingFailure: return "invalid_response"
    case .rateLimited, .concurrentRequests: return "busy"
    default: return "generation_failed"
    }
}

@main
struct AppleFoundationModelsWorker {
    static func main() async {
        let data = FileHandle.standardInput.readDataToEndOfFile()
        guard data.count <= 524288,
              let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let action = request["action"] as? String,
              action == "status" || action == "complete" else {
            emit(["ok": false, "reason_code": "invalid_request"])
            return
        }
        guard #available(macOS 26.0, *) else {
            emit(["ok": false, "reason_code": "unsupported_macos"])
            return
        }
        // Explicitly use the on-device model. Never select a cloud model or tools.
        let model = SystemLanguageModel.default
        switch model.availability {
        case .available: break
        case .unavailable(let reason):
            let code = unavailableReason(reason)
            emit(action == "status"
                 ? ["ok": true, "available": false, "reason_code": code]
                 : ["ok": false, "reason_code": code])
            return
        @unknown default:
            emit(["ok": false, "reason_code": "model_unavailable"])
            return
        }
        if action == "status" {
            emit(["ok": true, "available": true, "reason_code": "available"])
            return
        }
        guard let prompt = request["prompt"] as? String,
              let instructions = request["system_prompt"] as? String,
              !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              prompt.utf8.count + instructions.utf8.count <= 131072 else {
            emit(["ok": false, "reason_code": "invalid_request"])
            return
        }
        let maximumTokens = min(max((request["max_tokens"] as? Int) ?? 1024, 1), 4096)
        do {
            // Each request has its own context; earlier translations are not retained.
            let session = LanguageModelSession(model: model, instructions: instructions)
            let options = GenerationOptions(temperature: 0.1, maximumResponseTokens: maximumTokens)
            let response = try await session.respond(to: prompt, options: options)
            let text = response.content.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else {
                emit(["ok": false, "reason_code": "empty_response"])
                return
            }
            emit(["ok": true, "content": text])
        } catch {
            // Native errors may contain the source prompt; expose only a stable code.
            emit(["ok": false, "reason_code": generationReason(error)])
        }
    }
}
