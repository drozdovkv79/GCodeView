import Foundation
import simd

class GCodeParser {
    
    private struct ParserState {
        var points: [GCodePoint] = []
        var stats = GCodeStats()
        var currentLayer = 0
        var lastZ: Float = 0
        var x: Float = 0, y: Float = 0, z: Float = 0, e: Float = 0, f: Float = 0
        
        var extMinX: Float = .greatestFiniteMagnitude, extMaxX: Float = -.greatestFiniteMagnitude
        var extMinY: Float = .greatestFiniteMagnitude, extMaxY: Float = -.greatestFiniteMagnitude
        var extMinZ: Float = .greatestFiniteMagnitude, extMaxZ: Float = -.greatestFiniteMagnitude
        var totalE: Float = 0
        var maxSpeed: Float = 0
        
        var prevPoint: GCodePoint? = nil
        var extPathLength: Float = 0
        var travPathLength: Float = 0
        var printTime: Float = 0
    }
    
    static func parse(file: URL, progress: @escaping (Double) -> Void) -> (points: [GCodePoint], stats: GCodeStats) {
        var state = ParserState()
        state.points.reserveCapacity(1_000_000)
        
        let startTime = CFAbsoluteTimeGetCurrent()
        
        guard let data = try? Data(contentsOf: file, options: .alwaysMapped) else {
            return (state.points, state.stats)
        }
        
        let readTime = CFAbsoluteTimeGetCurrent()
        
        let totalBytes = data.count
        var lastProgressByte = 0
        let progressStep = totalBytes / 20
        
        data.withUnsafeBytes { rawBufferPointer in
            let bytes = rawBufferPointer.bindMemory(to: UInt8.self)
            var lineStart = 0
            
            for i in 0..<totalBytes {
                let byte = bytes[i]
                if byte == 10 || byte == 13 {
                    if i > lineStart {
                        processLine(bytes: bytes, start: lineStart, end: i, state: &state)
                    }
                    lineStart = i + 1
                    
                    if i - lastProgressByte > progressStep {
                        lastProgressByte = i
                        progress(Double(i) / Double(totalBytes) * 50.0)
                    }
                }
            }
            if totalBytes > lineStart {
                processLine(bytes: bytes, start: lineStart, end: totalBytes, state: &state)
            }
        }
        
        let parseTime = CFAbsoluteTimeGetCurrent()
        
        if state.stats.extrusionPoints > 0 {
            state.stats.width = state.extMaxX - state.extMinX
            state.stats.length = state.extMaxY - state.extMinY
            state.stats.height = state.extMaxZ - state.extMinZ
            state.stats.maxZ = state.extMaxZ
            state.stats.centerOfMassX = state.extMinX + state.stats.width / 2.0
            state.stats.centerOfMassY = state.extMinY + state.stats.length / 2.0
        } else {
            state.stats.width = 0; state.stats.length = 0; state.stats.height = 0; state.stats.maxZ = 0
        }
        
        state.stats.numLayers = state.currentLayer + 1
        state.stats.totalMaterial = state.totalE
        
        let filamentDiameter: Float = 1.75
        let filamentArea = Float.pi * (filamentDiameter / 2) * (filamentDiameter / 2)
        state.stats.volume = state.totalE * filamentArea
        
        state.stats.maxSpeed = state.maxSpeed
        state.stats.extrusionPathLength = state.extPathLength
        state.stats.travelPathLength = state.travPathLength
        state.stats.estimatedPrintTimeMin = state.printTime / 60.0
        state.stats.averageFlowRate = state.extPathLength > 0 ? (state.stats.volume / state.extPathLength) : 0
        state.stats.boundingBoxVolume = state.stats.width * state.stats.length * state.stats.height
        state.stats.xyFootprintArea = state.stats.width * state.stats.length
        state.stats.modelCompactness = state.stats.boundingBoxVolume > 0 ? (state.stats.volume / state.stats.boundingBoxVolume) : 0
        
        progress(100.0)
        
        let endTime = CFAbsoluteTimeGetCurrent()
        print("⏱ File Read: \(String(format: "%.2f", (readTime - startTime) * 1000)) ms")
        print("⏱ Parsing: \(String(format: "%.2f", (parseTime - readTime) * 1000)) ms")
        print("⏱ Stats Calc: \(String(format: "%.2f", (endTime - parseTime) * 1000)) ms")
        
        return (state.points, state.stats)
    }
    
    @inline(__always)
    private static func processLine(bytes: UnsafeBufferPointer<UInt8>, start: Int, end: Int, state: inout ParserState) {
        guard end - start > 3 else { return }
        var idx = start
        
        while idx < end && bytes[idx] == 32 { idx += 1 }
        guard idx < end && bytes[idx] == 71 else { return }
        idx += 1
        guard idx < end && (bytes[idx] == 48 || bytes[idx] == 49) else { return }
        let isG1 = bytes[idx] == 49
        idx += 1
        guard idx < end && (bytes[idx] == 32 || bytes[idx] == 9) else { return }
        
        var posX: Float? = nil, posY: Float? = nil, posZ: Float? = nil, posE: Float? = nil, posF: Float? = nil
        
        while idx < end {
            let c = bytes[idx]
            if c == 59 { return }
            
            if c == 88 || c == 89 || c == 90 || c == 69 || c == 70 {
                let param = c
                idx += 1
                if let val = parseFloat(bytes: bytes, start: idx, end: end) {
                    switch param {
                    case 88: posX = val
                    case 89: posY = val
                    case 90: posZ = val
                    case 69: posE = val
                    case 70: posF = val
                    default: break
                    }
                }
            }
            idx += 1
        }
        
        if let v = posX { state.x = v }
        if let v = posY { state.y = v }
        if let v = posZ {
            state.z = v
            if abs(state.z - state.lastZ) > 1.0 {
                state.currentLayer += 1
                state.lastZ = state.z
            }
        }
        if let v = posE { state.e = v }
        if let v = posF { state.f = v }
        
        let hasExtrusion = isG1 && state.e > 0
        let point = GCodePoint(x: state.x, y: state.y, z: state.z, e: state.e, feedRate: state.f, layer: state.currentLayer, isExtrusion: hasExtrusion)
        
        state.points.append(point)
        state.stats.totalPoints += 1
        
        if hasExtrusion {
            state.stats.extrusionPoints += 1
            if state.x < state.extMinX { state.extMinX = state.x }; if state.x > state.extMaxX { state.extMaxX = state.x }
            if state.y < state.extMinY { state.extMinY = state.y }; if state.y > state.extMaxY { state.extMaxY = state.y }
            if state.z < state.extMinZ { state.extMinZ = state.z }; if state.z > state.extMaxZ { state.extMaxZ = state.z }
            state.totalE += state.e
            if state.f > state.maxSpeed { state.maxSpeed = state.f }
        } else {
            state.stats.travelPoints += 1
        }
        
        if let prev = state.prevPoint {
            let dx = point.x - prev.x
            let dy = point.y - prev.y
            let dz = point.z - prev.z
            let dist = sqrt(dx*dx + dy*dy + dz*dz)
            let speed = point.feedRate > 0 ? point.feedRate : 1000.0
            
            if point.isExtrusion {
                state.extPathLength += dist
                state.printTime += (dist / speed) * 60.0
            } else {
                state.travPathLength += dist
                state.printTime += (dist / speed) * 60.0
            }
        }
        state.prevPoint = point
    }
    
    @inline(__always)
    private static func parseFloat(bytes: UnsafeBufferPointer<UInt8>, start: Int, end: Int) -> Float? {
        var i = start
        var val: Float = 0
        var sign: Float = 1
        var hasDigits = false
        
        if i < end && bytes[i] == 45 { sign = -1; i += 1 }
        while i < end {
            let c = bytes[i]
            if c >= 48 && c <= 57 {
                val = val * 10 + Float(c - 48)
                hasDigits = true
                i += 1
            } else { break }
        }
        if i < end && bytes[i] == 46 {
            i += 1
            var dec: Float = 0.1
            while i < end {
                let c = bytes[i]
                if c >= 48 && c <= 57 {
                    val += Float(c - 48) * dec
                    dec *= 0.1
                    hasDigits = true
                    i += 1
                } else { break }
            }
        }
        return hasDigits ? sign * val : nil
    }
}
