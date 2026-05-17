import Foundation
import simd

class GCodeParser {
    static func parse(file: URL, progress: @escaping (Double) -> Void) -> (points: [GCodePoint], stats: GCodeStats) {
        guard let content = try? String(contentsOf: file) else { return ([], GCodeStats()) }
        let lines = content.components(separatedBy: .newlines)
        
        var points: [GCodePoint] = []
        var currentLayer = 0
        var lastZ: Float = 0
        let layerThreshold: Float = 1.0
        
        var x: Float = 0, y: Float = 0, z: Float = 0, e: Float = 0, f: Float = 0
        
        for (index, line) in lines.enumerated() {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty || trimmed.hasPrefix(";") { continue }
            if trimmed.contains("M82") || trimmed.contains("M83") { continue }
            
            if trimmed.hasPrefix("G0 ") || trimmed.hasPrefix("G1 ") {
                let isG1 = trimmed.hasPrefix("G1 ")
                
                if let match = extractValue(from: trimmed, prefix: "X") { x = match }
                if let match = extractValue(from: trimmed, prefix: "Y") { y = match }
                if let match = extractValue(from: trimmed, prefix: "Z") {
                    z = match
                    if abs(z - lastZ) > layerThreshold {
                        currentLayer += 1
                        lastZ = z
                    }
                }
                if let match = extractValue(from: trimmed, prefix: "E") { e = match }
                if let match = extractValue(from: trimmed, prefix: "F") { f = match }
                
                let hasExtrusion = isG1 && e > 0
                points.append(GCodePoint(x: x, y: y, z: z, e: e, feedRate: f, layer: currentLayer, isExtrusion: hasExtrusion))
            }
            
            if index % 1000 == 0 { progress(Double(index) / Double(lines.count) * 50.0) }
        }
        
        let stats = calculateStats(points: points)
        progress(100.0)
        return (points, stats)
    }
    
    private static func extractValue(from line: String, prefix: String) -> Float? {
        guard let range = line.range(of: "\(prefix)[0-9\\-\\.]+", options: .regularExpression) else { return nil }
        let numStr = line[range].dropFirst(prefix.count)
        return Float(numStr)
    }
    
    private static func calculateStats(points: [GCodePoint]) -> GCodeStats {
        var stats = GCodeStats()
        stats.totalPoints = points.count
        let extPts = points.filter { $0.isExtrusion }
        let travPts = points.filter { !$0.isExtrusion }
        
        stats.extrusionPoints = extPts.count
        stats.travelPoints = travPts.count
        
        if extPts.isEmpty { return stats }
        
        let xs = extPts.map { $0.x }
        let ys = extPts.map { $0.y }
        let zs = extPts.map { $0.z }
        
        stats.width = xs.max()! - xs.min()!
        stats.length = ys.max()! - ys.min()!
        stats.height = zs.max()! - zs.min()!
        stats.numLayers = Set(extPts.map { $0.layer }).count
        stats.totalMaterial = extPts.map { $0.e }.reduce(0, +)
        
        let filamentDiameter: Float = 1.75
        let filamentArea = Float.pi * (filamentDiameter / 2) * (filamentDiameter / 2)
        stats.volume = stats.totalMaterial * filamentArea
        
        stats.maxZ = zs.max()!
        stats.maxSpeed = extPts.map { $0.feedRate }.max()!
        
        // --- РАСШИРЕННАЯ АНАЛИТИКА ---
        
        // 1 & 2. Длины путей
        var extPathLength: Float = 0
        var travPathLength: Float = 0
        
        // 3. Время (в минутах)
        var printTime: Float = 0
        
        // 7 & 8. Центр масс (среднее по экструзии)
        stats.centerOfMassX = xs.reduce(0, +) / Float(xs.count)
        stats.centerOfMassY = ys.reduce(0, +) / Float(ys.count)
        
        // 9. Острые углы
        var sharpCorners = 0
        
        // Вспомогательные переменные для расчетов
        var prevExt: GCodePoint? = nil
        var prevPrevExt: GCodePoint? = nil
        var prevPoint: GCodePoint? = nil
        
        for pt in points {
            if let prev = prevPoint {
                let dx = pt.x - prev.x
                let dy = pt.y - prev.y
                let dz = pt.z - prev.z
                let dist = sqrt(dx*dx + dy*dy + dz*dz)
                let speedMmPerMin = pt.feedRate > 0 ? pt.feedRate : 1000.0 // дефолтная скорость для G0
                
                if pt.isExtrusion {
                    extPathLength += dist
                    printTime += (dist / speedMmPerMin) * 60.0 // в секундах
                    
                    // Проверка острых углов
                    if let prev2 = prevPrevExt, prev2.layer == pt.layer {
                        let v1 = simd_float2(prev.x - prev2.x, prev.y - prev2.y)
                        let v2 = simd_float2(pt.x - prev.x, pt.y - prev.y)
                        let l1 = simd_length(v1), l2 = simd_length(v2)
                        if l1 > 0.01 && l2 > 0.01 {
                            let dot = simd_dot(v1/l1, v2/l2)
                            let angle = acos(min(max(dot, -1.0), 1.0)) * (180.0 / Float.pi)
                            if angle < 120.0 { sharpCorners += 1 }
                        }
                    }
                    prevPrevExt = prevExt
                    prevExt = pt
                    
                } else {
                    travPathLength += dist
                    printTime += (dist / speedMmPerMin) * 60.0
                }
            }
            prevPoint = pt
        }
        
        stats.extrusionPathLength = extPathLength
        stats.travelPathLength = travPathLength
        stats.estimatedPrintTimeMin = printTime / 60.0 // переводим в минуты
        stats.sharpCornersCount = sharpCorners
        
        // 4. Средний расход на мм (мм³/мм)
        stats.averageFlowRate = extPathLength > 0 ? (stats.volume / extPathLength) : 0
        
        // 5. Объем BoundingBox
        stats.boundingBoxVolume = stats.width * stats.length * stats.height
        
        // 6. Площадь опорной площадки
        stats.xyFootprintArea = stats.width * stats.length
        
        // 10. Компактность
        stats.modelCompactness = stats.boundingBoxVolume > 0 ? (stats.volume / stats.boundingBoxVolume) : 0
        
        return stats
    }
}
