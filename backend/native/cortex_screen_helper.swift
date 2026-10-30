import Foundation
import AppKit
import ApplicationServices
import Vision
import ScreenCaptureKit

// MARK: - Data Models

struct AppInfo: Codable {
    let bundleId: String?
    let name: String
    let pid: Int32
    let isActive: Bool
    let isHidden: Bool
}

struct RectBounds: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct WindowInfo: Codable {
    let windowId: Int
    let pid: Int32
    let appName: String
    let title: String?
    let bounds: RectBounds
    let isOnScreen: Bool
    let layer: Int
}

struct AXElementInfo: Codable {
    let id: String
    let role: String
    let subrole: String?
    let title: String?
    let value: String?
    let descriptionText: String?
    let bounds: RectBounds?
    let isEnabled: Bool
    let actions: [String]
    let depth: Int
    let path: String
}

struct OCRObservation: Codable {
    let text: String
    let confidence: Float
    let bounds: RectBounds
    let normalizedBounds: RectBounds
    let languages: [String]
}

struct PermissionState: Codable {
    let accessibility: Bool
    let screenRecording: Bool
    let statusMessage: String
}

struct CommandResult<T: Codable>: Codable {
    let ok: Bool
    let error: String?
    let data: T?
    let timestamp: String
}

func nowISO() -> String {
    let formatter = ISO8601DateFormatter()
    return formatter.string(from: Date())
}

// MARK: - Permission Checking

func checkPermissions(requestScreen: Bool = false) -> PermissionState {
    let axTrusted = AXIsProcessTrusted()
    var screenRecording = false
    if #available(macOS 10.15, *) {
        screenRecording = CGPreflightScreenCaptureAccess()
        if !screenRecording && requestScreen {
            CGRequestScreenCaptureAccess()
        }
    }
    
    var msg = "Accessibility: \(axTrusted ? "GRANTED" : "DENIED"), Screen Recording: \(screenRecording ? "GRANTED" : "DENIED")"
    if !axTrusted {
        msg += " — Grant Accessibility in System Settings → Privacy & Security → Accessibility."
    }
    if !screenRecording {
        msg += " — Grant Screen Recording in System Settings → Privacy & Security → Screen Recording."
    }
    return PermissionState(accessibility: axTrusted, screenRecording: screenRecording, statusMessage: msg)
}

// MARK: - App & Window Enumeration

func getFrontmostApp() -> AppInfo? {
    guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
    return AppInfo(
        bundleId: app.bundleIdentifier,
        name: app.localizedName ?? "Unknown",
        pid: app.processIdentifier,
        isActive: app.isActive,
        isHidden: app.isHidden
    )
}

func listRunningApps() -> [AppInfo] {
    let apps = NSWorkspace.shared.runningApplications
    return apps.compactMap { app in
        guard app.activationPolicy == .regular else { return nil }
        return AppInfo(
            bundleId: app.bundleIdentifier,
            name: app.localizedName ?? "Unknown",
            pid: app.processIdentifier,
            isActive: app.isActive,
            isHidden: app.isHidden
        )
    }
}

func listWindows() -> [WindowInfo] {
    guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        return []
    }
    var windows: [WindowInfo] = []
    for dict in list {
        let winId = dict[kCGWindowNumber as String] as? Int ?? 0
        let pid = dict[kCGWindowOwnerPID as String] as? Int32 ?? 0
        let appName = dict[kCGWindowOwnerName as String] as? String ?? ""
        let title = dict[kCGWindowName as String] as? String
        let layer = dict[kCGWindowLayer as String] as? Int ?? 0
        let isOnScreen = dict[kCGWindowIsOnscreen as String] as? Bool ?? true
        
        var bounds = RectBounds(x: 0, y: 0, width: 0, height: 0)
        if let boundsDict = dict[kCGWindowBounds as String] as? [String: Any],
           let x = boundsDict["X"] as? Double,
           let y = boundsDict["Y"] as? Double,
           let w = boundsDict["Width"] as? Double,
           let h = boundsDict["Height"] as? Double {
            bounds = RectBounds(x: x, y: y, width: w, height: h)
        }
        
        windows.append(WindowInfo(
            windowId: winId,
            pid: pid,
            appName: appName,
            title: title,
            bounds: bounds,
            isOnScreen: isOnScreen,
            layer: layer
        ))
    }
    return windows
}

// MARK: - AXUIElement Inspection

func getAXAttribute<T>(_ element: AXUIElement, _ attribute: String) -> T? {
    var valueRef: CFTypeRef?
    let res = AXUIElementCopyAttributeValue(element, attribute as CFString, &valueRef)
    guard res == .success, let val = valueRef as? T else { return nil }
    return val
}

func getAXBounds(_ element: AXUIElement) -> RectBounds? {
    var posRef: CFTypeRef?
    var sizeRef: CFTypeRef?
    let posRes = AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &posRef)
    let sizeRes = AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &sizeRef)
    
    guard posRes == .success, sizeRes == .success,
          let posVal = posRef, let sizeVal = sizeRef else { return nil }
    
    var pos = CGPoint.zero
    var size = CGSize.zero
    if AXValueGetType(posVal as! AXValue) == .cgPoint {
        AXValueGetValue(posVal as! AXValue, .cgPoint, &pos)
    }
    if AXValueGetType(sizeVal as! AXValue) == .cgSize {
        AXValueGetValue(sizeVal as! AXValue, .cgSize, &size)
    }
    return RectBounds(x: Double(pos.x), y: Double(pos.y), width: Double(size.width), height: Double(size.height))
}

func inspectAXElementTree(pid: Int32, maxDepth: Int = 4, maxElements: Int = 150) -> [AXElementInfo] {
    let appElement = AXUIElementCreateApplication(pid)
    var elements: [AXElementInfo] = []
    
    func traverse(_ element: AXUIElement, depth: Int, path: String) {
        if elements.count >= maxElements || depth > maxDepth { return }
        
        let role: String = getAXAttribute(element, kAXRoleAttribute) ?? "AXUnknown"
        let subrole: String? = getAXAttribute(element, kAXSubroleAttribute)
        let title: String? = getAXAttribute(element, kAXTitleAttribute)
        var valueText: String? = nil
        if let strVal: String = getAXAttribute(element, kAXValueAttribute) {
            valueText = strVal
        } else if let intVal: Int = getAXAttribute(element, kAXValueAttribute) {
            valueText = String(intVal)
        }
        let desc: String? = getAXAttribute(element, kAXDescriptionAttribute)
        let bounds = getAXBounds(element)
        let isEnabled: Bool = getAXAttribute(element, kAXEnabledAttribute) ?? true
        
        var actions: [String] = []
        var actionNamesRef: CFArray?
        if AXUIElementCopyActionNames(element, &actionNamesRef) == .success,
           let names = actionNamesRef as? [String] {
            actions = names
        }
        
        let id = "\(role)_\(depth)_\(elements.count)"
        elements.append(AXElementInfo(
            id: id,
            role: role,
            subrole: subrole,
            title: title,
            value: valueText,
            descriptionText: desc,
            bounds: bounds,
            isEnabled: isEnabled,
            actions: actions,
            depth: depth,
            path: path
        ))
        
        // Children
        if let children: [AXUIElement] = getAXAttribute(element, kAXChildrenAttribute) {
            for (idx, child) in children.enumerated() {
                if elements.count >= maxElements { break }
                traverse(child, depth: depth + 1, path: "\(path)/\(idx)")
            }
        }
    }
    
    // Start traversal from application element
    traverse(appElement, depth: 0, path: "0")
    return elements
}

// MARK: - Apple Vision OCR

func performOCR(imagePath: String, recognitionLevel: VNRequestTextRecognitionLevel = .accurate) -> [OCRObservation] {
    guard FileManager.default.fileExists(atPath: imagePath),
          let image = NSImage(contentsOfFile: imagePath),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return []
    }
    
    let imgWidth = Double(cgImage.width)
    let imgHeight = Double(cgImage.height)
    var results: [OCRObservation] = []
    let semaphore = DispatchSemaphore(value: 0)
    
    let request = VNRecognizeTextRequest { (req, err) in
        defer { semaphore.signal() }
        guard let observations = req.results as? [VNRecognizedTextObservation] else { return }
        
        for obs in observations {
            guard let topCandidate = obs.topCandidates(1).first else { continue }
            let bbox = obs.boundingBox
            // Normalized Vision coords: (0,0) is bottom-left
            let normBounds = RectBounds(
                x: Double(bbox.origin.x),
                y: Double(bbox.origin.y),
                width: Double(bbox.size.width),
                height: Double(bbox.size.height)
            )
            // Screen / image pixel coords: (0,0) is top-left
            let pixelX = Double(bbox.origin.x) * imgWidth
            let pixelY = (1.0 - Double(bbox.origin.y) - Double(bbox.size.height)) * imgHeight
            let pixelW = Double(bbox.size.width) * imgWidth
            let pixelH = Double(bbox.size.height) * imgHeight
            
            let pixelBounds = RectBounds(
                x: pixelX,
                y: pixelY,
                width: pixelW,
                height: pixelH
            )
            
            results.append(OCRObservation(
                text: topCandidate.string,
                confidence: topCandidate.confidence,
                bounds: pixelBounds,
                normalizedBounds: normBounds,
                languages: []
            ))
        }
    }
    
    request.recognitionLevel = recognitionLevel
    request.usesLanguageCorrection = true
    
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
        semaphore.wait()
    } catch {
        return []
    }
    return results
}

// MARK: - Screenshot Capture

func captureScreen(targetPath: String, bounds: RectBounds? = nil) -> (ok: Bool, message: String) {
    let perms = checkPermissions()
    if !perms.screenRecording {
        // Fallback attempt via screencapture
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        var args = ["-x"]
        if let b = bounds {
            args.append("-R\(Int(b.x)),\(Int(b.y)),\(Int(b.width)),\(Int(b.height))")
        }
        args.append(targetPath)
        p.arguments = args
        do {
            try p.run()
            p.waitUntilExit()
            if p.terminationStatus == 0 && FileManager.default.fileExists(atPath: targetPath) {
                return (true, "Screenshot captured via system utility.")
            } else {
                return (false, perms.statusMessage)
            }
        } catch {
            return (false, "Screenshot failed: \(error.localizedDescription)")
        }
    }
    
    // When Screen Recording is granted, screencapture -x or ScreenCaptureKit captures full quality
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    var args = ["-x"]
    if let b = bounds {
        args.append("-R\(Int(b.x)),\(Int(b.y)),\(Int(b.width)),\(Int(b.height))")
    }
    args.append(targetPath)
    p.arguments = args
    do {
        try p.run()
        p.waitUntilExit()
        if p.terminationStatus == 0 && FileManager.default.fileExists(atPath: targetPath) {
            return (true, "Screenshot saved to \(targetPath)")
        } else {
            return (false, "screencapture exited with code \(p.terminationStatus)")
        }
    } catch {
        return (false, "Screenshot execution failed: \(error.localizedDescription)")
    }
}

// MARK: - AX Element Action Execution

func performAXAction(pid: Int32, path: String, actionName: String) -> (ok: Bool, message: String) {
    let appElement = AXUIElementCreateApplication(pid)
    let parts = path.split(separator: "/").compactMap { Int($0) }
    
    var current = appElement
    for (stepIndex, childIdx) in parts.enumerated() {
        if stepIndex == 0 { continue } // root is 0
        guard let children: [AXUIElement] = getAXAttribute(current, kAXChildrenAttribute),
              childIdx < children.count else {
            return (false, "AX element path navigation failed at step \(stepIndex) (index \(childIdx))")
        }
        current = children[childIdx]
    }
    
    let res = AXUIElementPerformAction(current, actionName as CFString)
    if res == .success {
        return (true, "AX action '\(actionName)' executed successfully.")
    } else {
        return (false, "AX action '\(actionName)' failed with status \(res.rawValue)")
    }
}

// MARK: - CLI & IPC Dispatcher

func outputJSON<T: Codable>(_ value: CommandResult<T>) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = .sortedKeys
    if let data = try? encoder.encode(value),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    } else {
        print("{\"ok\":false,\"error\":\"JSON encoding failed\",\"timestamp\":\"\(nowISO())\"}")
    }
}

func handleLine(_ line: String) {
    let parts = line.trimmingCharacters(in: .whitespacesAndNewlines).components(separatedBy: " ")
    guard let command = parts.first, !command.isEmpty else { return }
    
    switch command {
    case "permissions":
        let req = parts.contains("--request")
        let p = checkPermissions(requestScreen: req)
        outputJSON(CommandResult(ok: true, error: nil, data: p, timestamp: nowISO()))
        
    case "frontmost":
        let app = getFrontmostApp()
        outputJSON(CommandResult(ok: true, error: nil, data: app, timestamp: nowISO()))
        
    case "apps":
        let apps = listRunningApps()
        outputJSON(CommandResult(ok: true, error: nil, data: apps, timestamp: nowISO()))
        
    case "windows":
        let wins = listWindows()
        outputJSON(CommandResult(ok: true, error: nil, data: wins, timestamp: nowISO()))
        
    case "ax-tree":
        var pid = getFrontmostApp()?.pid ?? 0
        var depth = 4
        var maxElem = 150
        for (i, arg) in parts.enumerated() {
            if arg == "--pid", i + 1 < parts.count { pid = Int32(parts[i+1]) ?? pid }
            if arg == "--depth", i + 1 < parts.count { depth = Int(parts[i+1]) ?? depth }
            if arg == "--max", i + 1 < parts.count { maxElem = Int(parts[i+1]) ?? maxElem }
        }
        if pid <= 0 {
            outputJSON(CommandResult<[AXElementInfo]>(ok: false, error: "No valid process PID specified or frontmost app not found.", data: nil, timestamp: nowISO()))
            return
        }
        let elements = inspectAXElementTree(pid: pid, maxDepth: depth, maxElements: maxElem)
        outputJSON(CommandResult(ok: true, error: nil, data: elements, timestamp: nowISO()))
        
    case "ocr":
        guard parts.count > 1 else {
            outputJSON(CommandResult<[OCRObservation]>(ok: false, error: "Usage: ocr <image_path>", data: nil, timestamp: nowISO()))
            return
        }
        let path = parts[1]
        let obs = performOCR(imagePath: path)
        outputJSON(CommandResult(ok: true, error: nil, data: obs, timestamp: nowISO()))
        
    case "capture":
        let path = parts.count > 1 ? parts[1] : "/tmp/cortex_screen.png"
        let res = captureScreen(targetPath: path)
        outputJSON(CommandResult(ok: res.ok, error: res.ok ? nil : res.message, data: ["path": path, "message": res.message], timestamp: nowISO()))
        
    case "action":
        // action <pid> <path> <action_name>
        guard parts.count >= 4,
              let pid = Int32(parts[1]) else {
            outputJSON(CommandResult<[String: String]>(ok: false, error: "Usage: action <pid> <path> <action_name>", data: nil, timestamp: nowISO()))
            return
        }
        let axPath = parts[2]
        let act = parts[3]
        let res = performAXAction(pid: pid, path: axPath, actionName: act)
        outputJSON(CommandResult(ok: res.ok, error: res.ok ? nil : res.message, data: ["message": res.message], timestamp: nowISO()))
        
    case "ping":
        outputJSON(CommandResult(ok: true, error: nil, data: ["pong": "cortex-screen-helper"], timestamp: nowISO()))
        
    default:
        outputJSON(CommandResult<[String: String]>(ok: false, error: "Unknown command '\(command)'", data: nil, timestamp: nowISO()))
    }
}

// MARK: - Main Entry Point

let args = Array(CommandLine.arguments.dropFirst())

if args.isEmpty || args.contains("--ipc") {
    // IPC mode: read lines from standard input
    while let line = readLine() {
        if line == "quit" || line == "exit" { break }
        handleLine(line)
        fflush(stdout)
    }
} else {
    // Single-shot command mode
    let joined = args.joined(separator: " ")
    handleLine(joined)
}
