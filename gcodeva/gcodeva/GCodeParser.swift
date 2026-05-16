import Foundation

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
            
            if index % 1000 == 0 {
                progress(Double(index) / Double(lines.count) * 50.0)
            }
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
        stats.extrusionPoints = points.filter { $0.isExtrusion }.count
        stats.travelPoints = stats.totalPoints - stats.extrusionPoints
        
        let extPts = points.filter { $0.isExtrusion }
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
        
        return stats
    }
}