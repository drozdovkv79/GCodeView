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
    }
    
    static func parse(file: URL, progress: @escaping (Double) -> Void) -> [GCodePoint] {
        var state = ParserState()
        // Резервируем память с запасом (63МБ ~= 2 миллиона строк)
        state.points.reserveCapacity(2_000_000)
        
        let t0 = CFAbsoluteTimeGetCurrent()
        
        guard let data = try? Data(contentsOf: file, options: .alwaysMapped) else { return state.points }
        
        let t1 = CFAbsoluteTimeGetCurrent()
        
        let totalBytes = data.count
        var lastProgressByte = 0
        let progressStep = totalBytes / 20
        
        // ЧИСТАЯ АРИФМЕТИКА УКАЗАТЕЛЕЙ (Обход проверок границ Swift)
        data.withUnsafeBytes { rawBufferPointer in
            let basePtr = rawBufferPointer.baseAddress!.assumingMemoryBound(to: UInt8.self)
            var ptr = basePtr
            let endPtr = basePtr + totalBytes
            
            var lineStart = basePtr
            
            while ptr < endPtr {
                let byte = ptr.pointee
                if byte == 10 || byte == 13 { // \n или \r
                    if ptr > lineStart {
                        processLine(start: lineStart, end: ptr, state: &state)
                    }
                    
                    // Пропускаем все переносы строк подряд
                    lineStart = ptr + 1
                    while ptr < endPtr && (ptr.pointee == 10 || ptr.pointee == 13) {
                        ptr = ptr + 1
                        lineStart = ptr
                    }
                    
                    // Обновление прогресса
                    let bytesRead = ptr - basePtr
                    if bytesRead - lastProgressByte > progressStep {
                        lastProgressByte = bytesRead
                        progress(Double(bytesRead) / Double(totalBytes) * 50.0)
                    }
                } else {
                    ptr = ptr + 1
                }
            }
            
            // Обработка последней строки, если файл не кончается переносом
            if ptr > lineStart {
                processLine(start: lineStart, end: ptr, state: &state)
            }
        }
        
        let t2 = CFAbsoluteTimeGetCurrent()
        
        // Легкая статистика (миллисекунды)
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
        state.stats.maxSpeed = state.maxSpeed
        
        let t3 = CFAbsoluteTimeGetCurrent()
        
        // ЛОГ В КОНСОЛЬ XCODE
        print("⏱ 1. File Read (mmap): \(String(format: "%.2f", (t1 - t0) * 1000)) ms")
        print("⏱ 2. Pure Parsing Loop (Raw Ptrs): \(String(format: "%.2f", (t2 - t1) * 1000)) ms")
        print("⏱ 3. Light Stats Calc: \(String(format: "%.2f", (t3 - t2) * 1000)) ms")
        print("⏱ TOTAL PARSE TIME: \(String(format: "%.2f", (t3 - t0) * 1000)) ms")
        
        return state.points
    }
    
    @inline(__always)
    private static func processLine(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>, state: inout ParserState) {
        guard end - start > 3 else { return }
        var p = start
        
        // Пропускаем пробелы
        while p < end && p.pointee == 32 { p = p + 1 }
        
        guard p < end && p.pointee == 71 else { return } // 'G'
        p = p + 1
        guard p < end && (p.pointee == 48 || p.pointee == 49) else { return } // '0' или '1'
        let isG1 = p.pointee == 49
        p = p + 1
        guard p < end && (p.pointee == 32 || p.pointee == 9) else { return } // Пробел или Tab
        
        var posX: Float? = nil, posY: Float? = nil, posZ: Float? = nil, posE: Float? = nil, posF: Float? = nil
        
        while p < end {
            let c = p.pointee
            if c == 59 { return } // ';' комментарий
            
            if c == 88 || c == 89 || c == 90 || c == 69 || c == 70 { // X, Y, Z, E, F
                let param = c
                p = p + 1 // Перепрыгиваем букву параметра
                if let result = parseFloat(start: p, end: end) {
                    switch param {
                    case 88: posX = result.value
                    case 89: posY = result.value
                    case 90: posZ = result.value
                    case 69: posE = result.value
                    case 70: posF = result.value
                    default: break
                    }
                    p = result.nextPtr // Перепрыгиваем само число
                }
            } else {
                p = p + 1 // Идем к следующему символу
            }
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
        state.points.append(GCodePoint(x: state.x, y: state.y, z: state.z, e: state.e, feedRate: state.f, layer: state.currentLayer, isExtrusion: hasExtrusion))
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
    }
    
    @inline(__always)
    private static func parseFloat(start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>) -> (value: Float, nextPtr: UnsafePointer<UInt8>)? {
        var p = start
        var val: Float = 0
        var sign: Float = 1
        var hasDigits = false
        
        if p < end && p.pointee == 45 { sign = -1; p = p + 1 } // '-'
        while p < end {
            let c = p.pointee
            if c >= 48 && c <= 57 { // '0'-'9'
                val = val * 10 + Float(c - 48)
                hasDigits = true
                p = p + 1
            } else { break }
        }
        if p < end && p.pointee == 46 { // '.'
            p = p + 1
            var dec: Float = 0.1
            while p < end {
                let c = p.pointee
                if c >= 48 && c <= 57 {
                    val += Float(c - 48) * dec
                    dec *= 0.1
                    hasDigits = true
                    p = p + 1
                } else { break }
            }
        }
        if hasDigits {
            return (sign * val, p) // Возвращаем число и указатель на следующий за числом символ
        }
        return nil
    }
}
