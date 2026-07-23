import Foundation
import simd
import SwiftUI
import UniformTypeIdentifiers

// Рекомендуется пометить структуру как @frozen, чтобы компилятор максимально оптимизировал работу с ней
// @frozen
// struct GCodePoint { ... }

class GCodeParser {
    @EnvironmentObject var appState: AppState

    static func parse(file: URL, progress: @escaping (Double) -> Void) -> (points: [GCodePoint], temperatures: [String: Float]) {
        let t0 = CFAbsoluteTimeGetCurrent()
        
        guard let data = try? Data(contentsOf: file, options: .alwaysMapped) else { return ([], [:]) }
        let totalBytes = data.count
        
        var points = [GCodePoint]()
        points.reserveCapacity(totalBytes / 25) // ~40 байт на точку, берем с запасом
        
        var lineCount = 0
        var gcodeLines = 0
        var temperatures: [String: Float] = [:]
        temperatures.reserveCapacity(4) // Обычно нагревателей не больше 4-5

        // Оптимизация прогресса: обновляем не чаще чем раз в 2 МБ (или 1%, если файл меньше)
        let progressStep = max(totalBytes / 100, 2 * 1024 * 1024)
        var nextProgressUpdate = progressStep
        var lastProgressValue: Double = 0

        data.withUnsafeBytes { rawBuffer in
            guard let base = rawBuffer.baseAddress?.assumingMemoryBound(to: UInt8.self) else { return }
            let end = base + totalBytes
            var ptr = base
            var lineStart = base
            var state = ParserState()
            
            while ptr < end {
                let byte = ptr.pointee
                if byte == 10 || byte == 13 { // \n или \r
                    if ptr > lineStart {
                        lineCount += 1
                        
                        // ★ ОПТИМИЗАЦИЯ 1: Быстрый путь (Fast Path)
                        // Проверяем только первую букву строки, чтобы выбрать нужный парсер
                        let firstChar = lineStart.pointee
                        
                        if firstChar == 83 { // 'S' -> SET_HEATER_TEMPERATURE
                            parseTemperatureLine(start: lineStart, end: ptr, temperatures: &temperatures)
                        } else if firstChar == 71 { // 'G' -> G0 или G1
                            if processLineFast(start: lineStart, end: ptr, state: &state, points: &points) {
                                gcodeLines += 1
                            }
                        }
                    }
                    
                    ptr += 1
                    // Пропускаем парные \r\n или пустые строки
                    while ptr < end && (ptr.pointee == 10 || ptr.pointee == 13) { ptr += 1 }
                    lineStart = ptr
                    
                    // ★ ОПТИМИЗАЦИЯ 2: Грубое throttling обновления прогресса
                    let bytesRead = ptr - base
                    if bytesRead >= nextProgressUpdate {
                        nextProgressUpdate += progressStep
                        let currentProgress = Double(bytesRead) / Double(totalBytes) * 100
                        // Защита от одинаковых значений из-за округлений
                        if abs(currentProgress - lastProgressValue) > 0.1 {
                            lastProgressValue = currentProgress
                            DispatchQueue.main.async { progress(currentProgress) }
                        }
                    }
                } else {
                    ptr += 1
                }
            }
            
            // Обработка последней строки, если файл не заканчивается на \n
            if ptr > lineStart {
                let firstChar = lineStart.pointee
                if firstChar == 83 { parseTemperatureLine(start: lineStart, end: ptr, temperatures: &temperatures) }
                else if firstChar == 71 { _ = processLineFast(start: lineStart, end: ptr, state: &state, points: &points) }
            }
        }

        // Сообщаем 100%
        DispatchQueue.main.async { progress(100.0) }

        // ★ ОПТИМИЗАЦИЯ 3: Постобработка без sqrt
        let returnThresholdSq: Float = 8.0 * 8.0 // 64.0
        let minPointsPerLayer = 10
        
        var layerBoundaries: [Int] = [0]
        var currentLayerStartX: Float = points.first?.x ?? 0
        var currentLayerStartY: Float = points.first?.y ?? 0
        
        for i in 1..<points.count {
            let point = points[i]
            
            if point.x != 0 || point.y != 0 {
                let dx = point.x - currentLayerStartX
                let dy = point.y - currentLayerStartY
                let distanceSq = dx * dx + dy * dy // Сравниваем квадраты!
                
                if distanceSq <= returnThresholdSq {
                    let layerSize = i - layerBoundaries.last!
                    if layerSize >= minPointsPerLayer {
                        layerBoundaries.append(i)
                        currentLayerStartX = point.x
                        currentLayerStartY = point.y
                    }
                }
            }
        }
        
        if layerBoundaries.last != points.count {
            layerBoundaries.append(points.count)
        }
        
        // Два отдельных цикла работают быстрее одного вложенного из-за предсказателя ветвлений и кэша процессора
        for j in 0..<(layerBoundaries.count - 1) {
            let startIdx = layerBoundaries[j]
            let endIdx = layerBoundaries[j + 1]
            let layerNum = j + 1
            for i in startIdx..<endIdx {
                points[i].layer = layerNum
            }
        }
        
        return (points, temperatures)
    }
    
    private struct ParserState {
        var x: Float = 0, y: Float = 0, z: Float = 0, e: Float = 0, f: Float = 0
        var layer: Int = 0
        var lastZ: Float = 0
        var layerStartX: Float = 0
        var layerStartY: Float = 0
        var isFirstPoint: Bool = true
    }
    
    @inline(__always)
    private static func parseTemperatureLine(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>,
                                             temperatures: inout [String: Float]) {
        var p = start
        while p < end && p.pointee == 32 { p += 1 }
        guard p + 3 < end else { return }
        
        // Проверяем "SET"
        guard p.pointee == 83 else { return } // 'S'
        guard p.advanced(by: 1).pointee == 69 else { return } // 'E'
        guard p.advanced(by: 2).pointee == 84 else { return } // 'T'
        p += 3
        
        while p < end && p.pointee == 32 { p += 1 }
        
        // Проверяем "_HEATER_TEMPERATURE" через сравнение с памятью (опционально, можно оставить как было, это вызывается редко)
        let expected = "_HEATER_TEMPERATURE"
        let expectedBytes = Array(expected.utf8)
        guard p + expectedBytes.count <= end else { return }
        
        for char in expectedBytes {
            guard p.pointee == char else { return }
            p += 1
        }
        
        var heaterName: String?
        var targetTemp: Float?
        
        while p < end {
            while p < end && (p.pointee == 32 || p.pointee == 9) { p += 1 }
            guard p < end else { break }
            
            if p.pointee == 104 { // 'h' - heater
                p += 7 // Пропускаем "heater=" (7 символов)
                guard p < end && p.pointee == 34 else { break } // '"'
                p += 1
                let nameStart = p
                var nameLength = 0
                while p < end && p.pointee != 34 {
                    p += 1
                    nameLength += 1
                }
                guard p < end && p.pointee == 34 else { break }
                if nameLength > 0 {
                    let nameBytes = UnsafeBufferPointer(start: nameStart, count: nameLength)
                    heaterName = String(bytes: nameBytes, encoding: .utf8)
                }
                p += 1
            } else if p.pointee == 116 { // 't' - target
                p += 7 // Пропускаем "target=" (7 символов)
                let (val, next) = parseFloatFast(start: p, end: end)
                if let v = val { targetTemp = v }
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
        while p < end && p.pointee == 32 { p += 1 }
        guard p + 2 < end else { return false }
        guard p.pointee == 71 else { return false } // 'G'
        
        let cmd = p.advanced(by: 1).pointee
        guard cmd == 48 || cmd == 49 else { return false } // '0' или '1'
        let isG1 = (cmd == 49)
        
        p += 2
        if p < end && p.pointee != 32 && p.pointee != 9 { return false }
        
        var newX: Float?
        var newY: Float?
        var newZ: Float?
        var newE: Float?
        var newF: Float?
        
        while p < end {
            let c = p.pointee
            if c == 59 { break } // ';'
            
            if (c >= 88 && c <= 90) || c == 69 || c == 70 { // X, Y, Z, E, F
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
        if let z = newZ { state.z = z }
        if let e = newE { state.e = e }
        if let f = newF { state.f = f }
        
        let isExtrusion = isG1 && state.e > 0
        
        points.append(GCodePoint(x: state.x, y: state.y, z: state.z, e: state.e,
                                 feedRate: state.f, layer: 0, isExtrusion: isExtrusion))
        return true
    }
    
    private static let pow10Div: [Float] = [0, 0.1, 0.01, 0.001, 0.0001, 0.00001, 0.000001, 0.0000001, 0.00000001, 0.000000001]
    
    @inline(__always)
    private static func parseFloatFast(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>) -> (value: Float?, nextPtr: UnsafePointer<UInt8>) {
        var p = start
        guard p < end else { return (nil, p) }
        
        var sign: Float = 1
        if p.pointee == 45 { // '-'
            sign = -1
            p += 1
        } else if p.pointee == 43 { // '+'
            p += 1
        }
        
        var intPart: Int32 = 0
        var hasDigits = false
        while p < end {
            let b = p.pointee
            if b >= 48 && b <= 57 {
                // Защита от переполнения Int32 (хотя в GCode координаты больше 2147483647 не встречаются)
                if intPart < 214748364 {
                    intPart = intPart &* 10 &+ Int32(b &- 48)
                }
                hasDigits = true
                p += 1
            } else {
                break
            }
        }
        
        var result = Float(intPart)
        
        if p < end && p.pointee == 46 { // '.'
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
