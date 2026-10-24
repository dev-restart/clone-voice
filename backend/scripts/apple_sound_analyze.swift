import Foundation
import AVFoundation
import SoundAnalysis
import CoreMedia
import Darwin

private enum HelperError: Error { case failed(String) }
private struct Input: Decodable { let audio_path: String }
private struct Frame: Encodable, Sendable {
    let start: Double
    let end: Double
    let speech: Double
    let music: Double
    let singing: Double
}
private struct Response: Encodable {
    let ok: Bool
    var frames: [Frame]? = nil
    var classifications: [String]? = nil
    var reason_code: String? = nil
}

private final class ResultsObserver: NSObject, SNResultsObserving, @unchecked Sendable {
    private let condition = NSCondition()
    private let duration: Double
    private let labels: [String]
    private var frames: [Frame] = []
    private var failure: String?
    private var requestComplete = false
    private var analyzerComplete = false

    init(duration: Double, labels: [String]) {
        self.duration = duration
        self.labels = labels
        super.init()
    }
    private func failLocked(_ code: String) {
        if failure == nil { failure = code }
        condition.broadcast()
    }
    func request(_ request: SNRequest, didProduce result: SNResult) {
        condition.lock()
        defer { condition.unlock() }
        guard failure == nil else { return }
        guard let result = result as? SNClassificationResult else {
            failLocked("invalid_result"); return
        }
        let start = CMTimeGetSeconds(result.timeRange.start)
        let end = CMTimeGetSeconds(CMTimeRangeGetEnd(result.timeRange))
        guard start.isFinite, end.isFinite, start >= 0, end > start, end <= duration + 1.001 else {
            failLocked("invalid_result"); return
        }
        guard start < duration else { return }
        guard frames.count < 8_000 else { failLocked("too_many_windows"); return }
        var scores: [String: Double] = [:]
        for label in labels {
            let value = result.classifications.first { $0.identifier == label }?.confidence ?? 0
            guard value.isFinite, (0...1).contains(value) else { failLocked("invalid_result"); return }
            scores[label] = value
        }
        frames.append(Frame(start: start, end: min(duration, end),
                            speech: scores["speech"] ?? 0, music: scores["music"] ?? 0, singing: scores["singing"] ?? 0))
    }
    func request(_ request: SNRequest, didFailWithError error: Error) {
        condition.lock()
        defer { condition.unlock() }
        failLocked("analysis_failed")
    }
    func requestDidComplete(_ request: SNRequest) {
        condition.lock()
        defer { condition.unlock() }
        requestComplete = true
        condition.broadcast()
    }
    func analyzerDidComplete(_ reachedEnd: Bool) {
        condition.lock()
        defer { condition.unlock() }
        analyzerComplete = true
        if !reachedEnd { failLocked("analysis_failed") }
        condition.broadcast()
    }
    func waitForResults(timeout: TimeInterval) throws -> [Frame] {
        condition.lock()
        defer { condition.unlock() }
        let deadline = Date().addingTimeInterval(timeout)
        while failure == nil && !(requestComplete && analyzerComplete) {
            guard condition.wait(until: deadline) else { throw HelperError.failed("analysis_timeout") }
        }
        if let failure { throw HelperError.failed(failure) }
        guard !frames.isEmpty else { throw HelperError.failed("no_frames") }
        return frames.sorted { $0.start == $1.start ? $0.end < $1.end : $0.start < $1.start }
    }
}

@main
enum AppleSoundAnalyze {
    private static func analyze() throws -> Response {
        let data = try FileHandle.standardInput.readToEnd() ?? Data()
        guard !data.isEmpty, data.count <= 16_384,
              let input = try? JSONDecoder().decode(Input.self, from: data),
              input.audio_path.hasPrefix("/"), input.audio_path.utf8.count <= 4_096,
              !input.audio_path.contains("\0") else { throw HelperError.failed("invalid_input") }
        let url = URL(fileURLWithPath: input.audio_path)
        let properties = try url.resourceValues(forKeys: [.isRegularFileKey])
        guard properties.isRegularFile == true else { throw HelperError.failed("invalid_audio") }
        let audio: AVAudioFile
        do { audio = try AVAudioFile(forReading: url) }
        catch { throw HelperError.failed("invalid_audio") }
        let rate = audio.processingFormat.sampleRate
        guard rate.isFinite, rate > 0, audio.length > 0 else { throw HelperError.failed("invalid_audio") }
        let duration = Double(audio.length) / rate
        guard duration.isFinite, duration > 0 else { throw HelperError.failed("invalid_audio") }
        guard duration <= 3_600 else { throw HelperError.failed("audio_too_long") }
        let request: SNClassifySoundRequest
        do { request = try SNClassifySoundRequest(classifierIdentifier: .version1) }
        catch { throw HelperError.failed("classifier_unavailable") }
        let known = Set(request.knownClassifications)
        let labels = ["speech", "music", "singing"].filter { known.contains($0) }
        guard labels.contains("speech") else { throw HelperError.failed("unsupported_classifications") }
        request.windowDuration = CMTime(seconds: 1, preferredTimescale: 48_000)
        request.overlapFactor = 0.5
        let observer = ResultsObserver(duration: duration, labels: labels)
        let analyzer = try SNAudioFileAnalyzer(url: url)
        defer { analyzer.cancelAnalysis(); analyzer.removeAllRequests() }
        try analyzer.add(request, withObserver: observer)
        analyzer.analyze(completionHandler: { reachedEnd in observer.analyzerDidComplete(reachedEnd) })
        return Response(ok: true, frames: try observer.waitForResults(timeout: 290), classifications: labels)
    }
    static func main() {
        DispatchQueue.global(qos: .userInitiated).async {
            let response: Response
            do { response = try analyze() }
            catch HelperError.failed(let code) { response = Response(ok: false, reason_code: code) }
            catch { response = Response(ok: false, reason_code: "analysis_failed") }
            let fallback = Data(#"{"ok":false,"reason_code":"serialization_failed"}"#.utf8)
            let payload = (try? JSONEncoder().encode(response)) ?? fallback
            var output = Data("CLONE_VOICE_SOUND_ANALYSIS:".utf8)
            output.append(payload)
            output.append(0x0A)
            FileHandle.standardOutput.write(output)
            exit(0)
        }
        dispatchMain()
    }
}
