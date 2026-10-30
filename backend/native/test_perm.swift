import Foundation
import CoreGraphics

if let image = CGWindowListCreateImage(CGRect.infinite, .optionOnScreenOnly, kCGNullWindowID, .nominalResolution) {
    print("CGWindowListCreateImage width: \(image.width), height: \(image.height)")
} else {
    print("CGWindowListCreateImage failed (Screen Recording permission denied or display unavailable)")
}

if #available(macOS 10.15, *) {
    let canRecord = CGPreflightScreenCaptureAccess()
    print("CGPreflightScreenCaptureAccess: \(canRecord)")
}
