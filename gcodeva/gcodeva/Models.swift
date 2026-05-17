import Foundation
import simd
import SwiftUI
import Combine

struct GCodePoint {
    var x: Float = 0
    var y: Float = 0
    var z: Float = 0
    var e: Float = 0
    var feedRate: Float = 0
    var layer: Int = 0
    var isExtrusion: Bool = false
}

struct GCodeStats {
    var totalPoints: Int = 0
    var extrusionPoints: Int = 0
    var travelPoints: Int = 0
    
    var width: Float = 0
    var length: Float = 0
    var height: Float = 0
    
    var numLayers: Int = 0
    var totalMaterial: Float = 0
    var volume: Float = 0
    
    var maxZ: Float = 0
    var maxSpeed: Float = 0
    
    var originalExtrusionPoints: Int = 0
    var optimizedExtrusionPoints: Int = 0
    var optimizationReductionPercent: Double = 0
    
    var extrusionPathLength: Float = 0
    var travelPathLength: Float = 0
    var estimatedPrintTimeMin: Float = 0
    var averageFlowRate: Float = 0
    var boundingBoxVolume: Float = 0
    var xyFootprintArea: Float = 0
    var centerOfMassX: Float = 0
    var centerOfMassY: Float = 0
    var sharpCornersCount: Int = 0
    var modelCompactness: Float = 0
}

enum CameraAction {
    case none, front, back, top, bottom, left, right
    case iso1, iso2, iso3, iso4
    case rotate360
}

enum MaterialPreset: String, CaseIterable {
    case plastic = "Пластик"
    case gypsum = "Гипс"
    case wood = "Дерево"
    case steel = "Сталь"
    case fiberglass = "Стекловолокно"
    case glass = "Стекло"
    case ceramic = "Керамика"
    case carbon = "Карбон"
}

// Структура для списка файлов с размером и датой
struct FileItem: Identifiable {
    let id = UUID()
    let url: URL
    let name: String
    let size: Int64
    let date: Date
    
    var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: size, countStyle: .file)
    }
    var formattedDate: String {
        let f = DateFormatter()
        f.dateStyle = .short
        f.timeStyle = .short
        return f.string(from: date)
    }
}

enum SortOrder {
    case name, size, date
}

class AppState: ObservableObject {
    @Published var fileItems: [FileItem] = []
    @Published var sortOrder: SortOrder = .name
    
    @Published var currentDirectory: URL?
    @Published var selectedFileURL: URL? // Изменено для связи с FileItem
    @Published var rawPoints: [GCodePoint] = []
    @Published var stats: GCodeStats?
    @Published var isLoading: Bool = false
    @Published var progress: Double = 0
    @Published var logMessages: [String] = []
    
    @Published var tempTubeDiameter: Float = 4.0
    @Published var tempModelColor: Color = Color(hex: "#e9e5ce")!
    
    @Published var tubeDiameter: Float = 4.0
    @Published var modelColor: Color = Color(hex: "#e9e5ce")!
    @Published var renderTrigger: Int = 0
    
    @Published var cameraAction: CameraAction = .none
    @Published var selectedMaterial: MaterialPreset = .plastic
    
    // Видео
    @Published var isRecording: Bool = false
    
    var sortedFiles: [FileItem] {
        switch sortOrder {
        case .name: return fileItems.sorted { $0.name.lowercased() < $1.name.lowercased() }
        case .size: return fileItems.sorted { $0.size > $1.size }
        case .date: return fileItems.sorted { $0.date > $1.date }
        }
    }
    
    func log(_ message: String) {
        DispatchQueue.main.async {
            let time = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
            self.logMessages.append("[\(time)] \(message)")
        }
    }
    
    func loadSelectedFile() {
        guard let file = selectedFileURL else { return }
        isLoading = true
        log("Analyzing: \(file.lastPathComponent)")
        
        DispatchQueue.global(qos: .userInitiated).async {
            let result = GCodeParser.parse(file: file) { progress in
                DispatchQueue.main.async { self.progress = progress }
            }
            
            DispatchQueue.main.async {
                self.rawPoints = result.points
                self.stats = result.stats
                self.isLoading = false
                
                self.tubeDiameter = self.tempTubeDiameter
                self.modelColor = self.tempModelColor
                self.renderTrigger += 1
                
                self.calculateOptimizationStats()
                self.log("Analysis complete. \(result.points.count) points found.")
            }
        }
    }
    
    func applyDiameter() {
        tubeDiameter = tempTubeDiameter
        renderTrigger += 1
        log("Tube diameter updated to \(String(format: "%.1f", tubeDiameter)) mm")
    }
    
    func applyColor() {
        modelColor = tempModelColor
        renderTrigger += 1
        log("Model color updated")
    }
    
    func changeMaterial(_ material: MaterialPreset) {
        selectedMaterial = material
        renderTrigger += 1
        log("Material changed to \(material.rawValue)")
    }
    
    private func calculateOptimizationStats() {
        let extPts = rawPoints.filter { $0.isExtrusion }
        var layers: [Int: [simd_float3]] = [:]
        
        for point in extPts {
            let pos = simd_float3(Float(point.x), Float(point.z), Float(point.y))
            layers[point.layer, default: []].append(pos)
        }
        
        var originalCount = 0
        var optimizedCount = 0
        
        for (_, var points) in layers {
            originalCount += points.count
            removeCollinearPoints(from: &points, angleThresholdDeg: 5.0)
            optimizedCount += points.count
        }
        
        DispatchQueue.main.async {
            self.stats?.originalExtrusionPoints = originalCount
            self.stats?.optimizedExtrusionPoints = optimizedCount
            if originalCount > 0 {
                self.stats?.optimizationReductionPercent = (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0
            } else {
                self.stats?.optimizationReductionPercent = 0.0
            }
        }
    }
}

func removeCollinearPoints(from points: inout [simd_float3], angleThresholdDeg: Float) {
    guard points.count > 2 else { return }
    var filtered: [simd_float3] = [points[0]]
    for i in 1..<points.count - 1 {
        let p1 = filtered.last!
        let p2 = points[i]
        let p3 = points[i + 1]
        let v1 = p2 - p1
        let v2 = p3 - p2
        let len1 = simd_length(v1)
        let len2 = simd_length(v2)
        if len1 < 0.001 || len2 < 0.001 { continue }
        let dot = simd_dot(v1 / len1, v2 / len2)
        let angle = acos(min(max(dot, -1.0), 1.0)) * (180.0 / Float.pi)
        if angle > angleThresholdDeg { filtered.append(p2) }
    }
    filtered.append(points.last!)
    points = filtered
}

extension Color {
    init?(hex: String) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")
        var rgb: UInt64 = 0
        Scanner(string: hexSanitized).scanHexInt64(&rgb)
        self.init(
            red: Double((rgb & 0xFF0000) >> 16) / 255.0,
            green: Double((rgb & 0x00FF00) >> 8) / 255.0,
            blue: Double(rgb & 0x0000FF) / 255.0
        )
    }
}
