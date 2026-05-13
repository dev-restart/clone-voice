import Foundation
import AppKit
import Speech

struct TranscriptSegment: Codable {
    let start: Double
    let end: Double
    let text: String
}

struct TranscriptPayload: Codable {
    let text: String
    let segments: [TranscriptSegment]
}

struct ErrorPayload: Codable {
    let error: String
}

let args = CommandLine.arguments
let outputURL = args.count >= 5 && !args[4].isEmpty ? URL(fileURLWithPath: args[4]) : nil

func writeJSON<T: Encodable>(_ value: T) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    if let data = try? encoder.encode(value), let text = String(data: data, encoding: .utf8) {
        if let outputURL {
            try? data.write(to: outputURL)
        } else {
            print(text)
        }
    }
}

func fail(_ message: String, code: Int32 = 1) -> Never {
    writeJSON(ErrorPayload(error: message))
    exit(code)
}

guard args.count >= 2 else {
    fail("Usage: apple_speech_transcribe.swift <audio_path> [language] [require_on_device] [output_json_path]")
}

let audioURL = URL(fileURLWithPath: args[1])
let language = args.count >= 3 && !args[2].isEmpty ? args[2] : Locale.current.identifier
let requireOnDevice = args.count >= 4 && args[3] == "true"

guard FileManager.default.fileExists(atPath: audioURL.path) else {
    fail("Audio file was not found.")
}

NSApplication.shared.setActivationPolicy(.regular)
NSRunningApplication.current.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])

func waitUntil(timeoutSeconds: TimeInterval, condition: () -> Bool) -> Bool {
    let deadline = Date().addingTimeInterval(timeoutSeconds)
    while !condition() && Date() < deadline {
        RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.1))
    }
    return condition()
}

var authStatus: SFSpeechRecognizerAuthorizationStatus?
SFSpeechRecognizer.requestAuthorization { status in
    authStatus = status
}
if !waitUntil(timeoutSeconds: 30, condition: { authStatus != nil }) {
    fail("Apple Speech permission request timed out.")
}
guard authStatus == .authorized else {
    fail("Apple Speech permission was not granted. Current status: \(authStatus?.rawValue ?? -1)")
}

let locale = Locale(identifier: language)
guard let recognizer = SFSpeechRecognizer(locale: locale) else {
    fail("Apple Speech recognizer is not available for language: \(language)")
}
guard recognizer.isAvailable else {
    fail("Apple Speech recognizer is currently unavailable.")
}

let request = SFSpeechURLRecognitionRequest(url: audioURL)
request.shouldReportPartialResults = false
if #available(macOS 10.15, *) {
    if requireOnDevice {
        guard recognizer.supportsOnDeviceRecognition else {
            fail("Apple Speech on-device recognition is not supported for language: \(language)")
        }
        request.requiresOnDeviceRecognition = true
    }
}

var finalResult: SFSpeechRecognitionResult?
var finalError: Error?
var recognitionFinished = false

let task = recognizer.recognitionTask(with: request) { result, error in
    if let result {
        finalResult = result
        if result.isFinal {
            recognitionFinished = true
        }
    }
    if let error {
        finalError = error
        recognitionFinished = true
    }
}

if !waitUntil(timeoutSeconds: 180, condition: { recognitionFinished }) {
    task.cancel()
    fail("Apple Speech transcription timed out.")
}

if let finalError {
    fail("Apple Speech transcription failed: \(finalError.localizedDescription)")
}

guard let result = finalResult else {
    fail("Apple Speech did not return a transcription result.")
}

let formatted = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
let segments = result.bestTranscription.segments
    .map { segment in
        TranscriptSegment(
            start: segment.timestamp,
            end: segment.timestamp + segment.duration,
            text: segment.substring.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }
    .filter { !$0.text.isEmpty }

writeJSON(TranscriptPayload(text: formatted, segments: segments))
