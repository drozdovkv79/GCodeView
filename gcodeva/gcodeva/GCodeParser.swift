import Foundation
import simd
import SwiftUI
import UniformTypeIdentifiers

class GCodeParser {
    @EnvironmentObject var appState: AppState

    // Изменяем возвращаемый тип на кортеж (points, temperatures)
    static func parse(file: URL, progress: @escaping (Double) -> Void) -> (points: [GCodePoint], temperatures: [String: Float]) {
        let t0 = CFAbsoluteTimeGetCurrent()
        
        // 1. ЗАМЕР: чтение файла
        let readStart = CFAbsoluteTimeGetCurrent()
        guard let data = try? Data(contentsOf: file, options: .alwaysMapped) else { return ([], [:]) }
        let readTime = (CFAbsoluteTimeGetCurrent() - readStart) * 1000
        print("📊 [1] File read: \(String(format: "%.2f", readTime)) ms")
        
        let totalBytes = data.count
        print("📊 File size: \(ByteCountFormatter.string(fromByteCount: Int64(totalBytes), countStyle: .file))")
        
        // 2. ЗАМЕР: предварительное резервирование памяти
        let reserveStart = CFAbsoluteTimeGetCurrent()
        var points = [GCodePoint]()
        // Оценка: в GCode примерно 20-40 байт на точку
        let estimatedPoints = totalBytes / 25
        points.reserveCapacity(estimatedPoints)
        let reserveTime = (CFAbsoluteTimeGetCurrent() - reserveStart) * 1000
        print("📊 [2] Reserve memory: \(String(format: "%.2f", reserveTime)) ms, capacity: \(estimatedPoints)")
        
        // 3. ЗАМЕР: основной парсинг
        let parseStart = CFAbsoluteTimeGetCurrent()
        var lineCount = 0
        var gcodeLines = 0
        var temperatures: [String: Float] = [:]

        data.withUnsafeBytes { rawBuffer in
            let base = rawBuffer.baseAddress!.assumingMemoryBound(to: UInt8.self)
            var ptr = base
            let end = base + totalBytes
            var lineStart = base
            
            var state = ParserState()
            
            while ptr < end {
                let byte = ptr.pointee
                if byte == 10 || byte == 13 {
                    if ptr > lineStart {
                        lineCount += 1
                        // Проверяем на SET_HEATER_TEMPERATURE
                        parseTemperatureLine(start: lineStart, end: ptr, temperatures: &temperatures)
                        
                        if processLineFast(start: lineStart, end: ptr, state: &state, points: &points) {
                            gcodeLines += 1
                        }
                    }
                    ptr += 1
                    while ptr < end && (ptr.pointee == 10 || ptr.pointee == 13) {
                        ptr += 1
                    }
                    lineStart = ptr
                    
                    // Прогресс
                    let bytesRead = ptr - base
                    if bytesRead % (totalBytes / 100) == 0 {
                        DispatchQueue.main.async {
                            progress(Double(bytesRead) / Double(totalBytes) * 100)
                        }
                    }
                } else {
                    ptr += 1
                }
            }
            
            if ptr > lineStart {
                lineCount += 1
                if (lineCount<100) {parseTemperatureLine(start: lineStart, end: ptr, temperatures: &temperatures)}
                if processLineFast(start: lineStart, end: ptr, state: &state, points: &points) {
                    gcodeLines += 1
                }
            }
        }

        let parseTime = (CFAbsoluteTimeGetCurrent() - parseStart) * 1000
        print("📊 [3] Parsing: \(String(format: "%.2f", parseTime)) ms")
        print("📊   - Total lines: \(lineCount)")
        print("📊   - G-code lines: \(gcodeLines)")
        print("📊   - Points created: \(points.count)")
        print("📊   - Temperatures: \(temperatures)")
        
        // 4. ЗАМЕР: если нужно - постобработка
        let postStart = CFAbsoluteTimeGetCurrent()
        // (здесь пока ничего)
        let postTime = (CFAbsoluteTimeGetCurrent() - postStart) * 1000
        print("📊 [4] Post-processing: \(String(format: "%.2f", postTime)) ms")
        
        let totalTime = (CFAbsoluteTimeGetCurrent() - t0) * 1000
        print("📊 TOTAL: \(String(format: "%.2f", totalTime)) ms")
        print("📊 Points per second: \(String(format: "%.0f", Double(points.count) / (totalTime / 1000)))")
        
        return (points, temperatures)
    }
    
    private struct ParserState {
        var x: Float = 0, y: Float = 0, z: Float = 0, e: Float = 0, f: Float = 0
        var layer: Int = 0
        var lastZ: Float = 0
    }
    
    // Парсинг строки SET_HEATER_TEMPERATURE
    @inline(__always)
    private static func parseTemperatureLine(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>,
                                             temperatures: inout [String: Float]) {
        var p = start
        // Пропускаем пробелы
        while p < end && p.pointee == 32 { p += 1 }
        guard p + 3 < end else { return }
        
        // Проверяем "SET"
        guard p.pointee == 83 else { return } // 'S'
        p += 1
        guard p.pointee == 69 else { return } // 'E'
        p += 1
        guard p.pointee == 84 else { return } // 'T'
        p += 1
        
        // Пропускаем пробелы
        while p < end && p.pointee == 32 { p += 1 }
        
        // Проверяем "_HEATER_TEMPERATURE"
        let expected = "_HEATER_TEMPERATURE"
        var expectedPtr = expected.utf8.makeIterator()
        for _ in 0..<expected.count {
            guard p < end else { return }
            let expectedChar = expectedPtr.next()!
            if p.pointee != expectedChar { return }
            p += 1
        }
        
        // Парсим параметры
        var heaterName: String?
        var targetTemp: Float?
        
        while p < end {
            // Пропускаем пробелы
            while p < end && (p.pointee == 32 || p.pointee == 9) { p += 1 }
            guard p < end else { break }
            
            // Проверяем параметры
            if p.pointee == 104 { // 'h' - heater
                p += 1
                guard p < end && p.pointee == 101 else { break } // 'e'
                p += 1
                guard p < end && p.pointee == 97 else { break } // 'a'
                p += 1
                guard p < end && p.pointee == 116 else { break } // 't'
                p += 1
                guard p < end && p.pointee == 101 else { break } // 'e'
                p += 1
                guard p < end && p.pointee == 114 else { break } // 'r'
                p += 1
                guard p < end && p.pointee == 61 else { break } // '='
                p += 1
                
                // Читаем имя нагревателя в кавычках
                guard p < end && p.pointee == 34 else { break } // '"'
                p += 1
                let nameStart = p
                var nameLength = 0
                while p < end && p.pointee != 34 {
                    p += 1
                    nameLength += 1
                }
                guard p < end && p.pointee == 34 else { break } // '"'
                if nameLength > 0 {
                    let nameBytes = UnsafeBufferPointer(start: nameStart, count: nameLength)
                    heaterName = String(bytes: nameBytes, encoding: .utf8)
                }
                p += 1
                
            } else if p.pointee == 116 { // 't' - target
                p += 1
                guard p < end && p.pointee == 97 else { break } // 'a'
                p += 1
                guard p < end && p.pointee == 114 else { break } // 'r'
                p += 1
                guard p < end && p.pointee == 103 else { break } // 'g'
                p += 1
                guard p < end && p.pointee == 101 else { break } // 'e'
                p += 1
                guard p < end && p.pointee == 116 else { break } // 't'
                p += 1
                guard p < end && p.pointee == 61 else { break } // '='
                p += 1
                
                let (val, next) = parseFloatFast(start: p, end: end)
                if let v = val {
                    targetTemp = v
                }
                p = next
            } else {
                p += 1
            }
        }
        
        if let name = heaterName, let temp = targetTemp {
            temperatures[name] = temp
        }
    }
    
    @inline(__always)
    private static func processLineFast(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>,
                                        state: inout ParserState, points: inout [GCodePoint]) -> Bool {
        var p = start
        // Пропускаем пробелы
        while p < end && p.pointee == 32 { p += 1 }
        guard p + 2 < end else { return false }
        guard p.pointee == 71 else { return false } // 'G'
        p += 1
        let cmd = p.pointee
        guard cmd == 48 || cmd == 49 else { return false }
        let isG1 = (cmd == 49)
        p += 1
        // Пробел или таб
        if p < end && p.pointee != 32 && p.pointee != 9 { return false }
        
        var newX: Float?
        var newY: Float?
        var newZ: Float?
        var newE: Float?
        var newF: Float?
        
        while p < end {
            let c = p.pointee
            if c == 59 { break }
            
            // Быстрая проверка на допустимые буквы
            if (c >= 88 && c <= 90) || c == 69 || c == 70 { // X,Y,Z,E,F
                let param = c
                p += 1
                let (val, next) = parseFloatFast(start: p, end: end)
                if let v = val {
                    switch param {
                    case 88: newX = v
                    case 89: newY = v
                    case 90: newZ = v
                    case 69: newE = v
                    case 70: newF = v
                    default: break
                    }
                }
                p = next
            } else {
                p += 1
            }
        }
        
        if let x = newX { state.x = x }
        if let y = newY { state.y = y }
        if let z = newZ {
            state.z = z
            if abs(state.z - state.lastZ) > 1.0 {
                state.layer += 1
                state.lastZ = state.z
            }
        }
        if let e = newE { state.e = e }
        if let f = newF { state.f = f }
        
        let isExtrusion = isG1 && state.e > 0
        points.append(GCodePoint(x: state.x, y: state.y, z: state.z, e: state.e,
                                 feedRate: state.f, layer: state.layer, isExtrusion: isExtrusion))
        return true
    }
    
    private static let pow10Div: [Float] = [0, 0.1, 0.01, 0.001, 0.0001, 0.00001, 0.000001, 0.0000001, 0.00000001, 0.000000001]
    
    @inline(__always)
    private static func parseFloatFast(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>) -> (value: Float?, nextPtr: UnsafePointer<UInt8>) {
        var p = start
        guard p < end else { return (nil, p) }
        
        var sign: Float = 1
        if p.pointee == 45 {
            sign = -1
            p += 1
        }
        
        var intPart: Int32 = 0
        var hasDigits = false
        while p < end {
            let b = p.pointee
            if b >= 48 && b <= 57 {
                intPart = intPart &* 10 &+ Int32(b &- 48)
                hasDigits = true
                p += 1
            } else {
                break
            }
        }
        
        var result = Float(intPart)
        
        if p < end && p.pointee == 46 {
            p += 1
            var decPart: Int32 = 0
            var decCount = 0
            while p < end && decCount < 9 {
                let b = p.pointee
                if b >= 48 && b <= 57 {
                    decPart = decPart &* 10 &+ Int32(b &- 48)
                    decCount += 1
                    p += 1
                } else {
                    break
                }
            }
            if decCount > 0 {
                result += Float(decPart) * pow10Div[decCount]
            }
        }
        
        return hasDigits ? (sign * result, p) : (nil, p)
    }
}
