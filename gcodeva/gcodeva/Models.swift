import Foundation
import simd
import SwiftUI
import Combine
import SceneKit

struct GCodePoint { var x: Float = 0; var y: Float = 0; var z: Float = 0; var e: Float = 0; var feedRate: Float = 0; var layer: Int = 0; var isExtrusion: Bool = false }

struct GCodeStats {
    var totalPoints: Int = 0; var extrusionPoints: Int = 0; var travelPoints: Int = 0
    var width: Float = 0; var length: Float = 0; var height: Float = 0
    var numLayers: Int = 0; var totalMaterial: Float = 0; var volume: Float = 0
    var maxZ: Float = 0; var maxSpeed: Float = 0
    var originalExtrusionPoints: Int = 0; var optimizedExtrusionPoints: Int = 0; var optimizationReductionPercent: Double = 0
    var extrusionPathLength: Float = 0; var travelPathLength: Float = 0; var estimatedPrintTimeMin: Float = 0
    var averageFlowRate: Float = 0; var boundingBoxVolume: Float = 0; var xyFootprintArea: Float = 0
    var centerOfMassX: Float = 0; var centerOfMassY: Float = 0; var sharpCornersCount: Int = 0; var modelCompactness: Float = 0
}

enum CameraAction { case none, front, back, top, bottom, left, right, iso1, iso2, iso3, iso4, rotate360 }
enum MaterialPreset: String, CaseIterable { case matte = "Матовый"; case plastic = "Пластик"; case steel = "Сталь"; case glass = "Стекло" }

struct LayerMesh { let id: Int; let vertices: [SCNVector3]; let normals: [SCNVector3]; let indices: [Int32] }

struct FileItem: Identifiable {
    let id = UUID(); let url: URL; let name: String; let size: Int64; let date: Date
    var formattedSize: String { ByteCountFormatter.string(fromByteCount: size, countStyle: .file) }
    var formattedDate: String { let f = DateFormatter(); f.dateStyle = .short; f.timeStyle = .none; return f.string(from: date) }
}

enum SortOrder { case name, size, date }

class AppState: ObservableObject {
    @Published var fileItems: [FileItem] = []
    @Published var sortOrder: SortOrder = .name
    @Published var currentDirectory: URL?
    @Published var selectedFileURL: URL?
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
    @Published var selectedMaterial: MaterialPreset = .matte
    @Published var isRecording: Bool = false
    @Published var videoWidth: Int = 1920; @Published var videoHeight: Int = 1080
    @Published var showAxis: Bool = true
    @Published var modelSize: simd_float3 = simd_float3(1,1,1) // ИСПРАВЛЕНО: дефолт не 0
    
    @Published var processedLayers: [LayerMesh] = []
    @Published var modelBoundingBox: (min: simd_float3, max: simd_float3)? = nil
    
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
    
    func loadFilesFromDirectory(_ url: URL) {
        do {
            let urls = try FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey])
            var items: [FileItem] = []
            for fileURL in urls {
                let ext = fileURL.pathExtension.lowercased()
                guard ext == "gcode" || ext == "nc" || ext == "ngc" else { continue }
                let resources = try fileURL.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                items.append(FileItem(url: fileURL, name: fileURL.lastPathComponent, size: Int64(resources.fileSize ?? 0), date: resources.contentModificationDate ?? Date.distantPast))
            }
            DispatchQueue.main.async { self.fileItems = items; self.log("Found \(items.count) GCode files.") }
        } catch { log("Error reading directory: \(error)") }
    }
    
    func loadSelectedFile() {
        guard let file = selectedFileURL else { return }
        isLoading = true
        log("📂 Start analyzing: \(file.lastPathComponent)")
        let startTime = CFAbsoluteTimeGetCurrent()
        
        DispatchQueue.global(qos: .userInitiated).async {
            let result = GCodeParser.parse(file: file) { progress in
                DispatchQueue.main.async { self.progress = progress }
            }
            
            let parseEndTime = CFAbsoluteTimeGetCurrent()
            DispatchQueue.main.async {
                self.log("⏱ File Read & Parse: \(String(format: "%.2f", (parseEndTime - startTime) * 1000)) ms")
                
                self.rawPoints = result.points
                self.stats = result.stats
                self.tubeDiameter = self.tempTubeDiameter
                self.modelColor = self.tempModelColor
                
                DispatchQueue.global(qos: .userInitiated).async {
                    self.processGeometry()
                }
            }
        }
    }
    
    private func processGeometry() {
        let startTime = CFAbsoluteTimeGetCurrent()
        let extPts = rawPoints.filter { $0.isExtrusion }
        let radius = Float(tubeDiameter / 2.0)
        let segments = 8
        
        var layers: [Int: [simd_float3]] = [:]
        // ИСПРАВЛЕНО: Быстрый расчет Bounding Box математически
        var globalMin = simd_float3(repeating: Float.greatestFiniteMagnitude)
        var globalMax = simd_float3(repeating: -Float.greatestFiniteMagnitude)
        
        for point in extPts {
            let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
            layers[point.layer, default: []].append(pos)
            globalMin = simd_min(globalMin, pos)
            globalMax = simd_max(globalMax, pos)
        }
        
        let collinearStartTime = CFAbsoluteTimeGetCurrent()
        var meshes: [LayerMesh] = []
        meshes.reserveCapacity(layers.count)
        
        for (layerIndex, var points) in layers.sorted(by: { $0.key < $1.key }) {
            if points.count < 2 { continue }
            removeCollinearPoints(from: &points, angleThresholdDeg: 5.0)
            if points.count < 2 { continue }
            
            if let tubeData = createTubeBuffers(for: points, radius: radius, segments: segments) {
                meshes.append(LayerMesh(id: layerIndex, vertices: tubeData.v, normals: tubeData.n, indices: tubeData.i))
            }
        }
        
        let endTime = CFAbsoluteTimeGetCurrent()
        
        DispatchQueue.main.async {
            self.log("⏱ Collinear removal: \(String(format: "%.2f", (collinearStartTime - startTime) * 1000)) ms")
            self.log("⏱ Geometry buffers prep: \(String(format: "%.2f", (endTime - collinearStartTime) * 1000)) ms")
            
            self.processedLayers = meshes
            self.modelBoundingBox = (globalMin, globalMax)
            self.modelSize = globalMax - globalMin
            self.isLoading = false
            
            DispatchQueue.global(qos: .userInitiated).async { self.calculateOptimizationStats() }
            self.renderTrigger += 1
        }
    }
    
    func applyDiameter() {
        tubeDiameter = tempTubeDiameter
        log("Diameter changed. Reprocessing geometry...")
        DispatchQueue.global(qos: .userInitiated).async { self.processGeometry() }
    }
    
    func applyColor() { modelColor = tempModelColor; renderTrigger += 1; log("Model color updated") }
    func changeMaterial(_ material: MaterialPreset) { selectedMaterial = material; renderTrigger += 1; log("Material changed to \(material.rawValue)") }
    
    private func calculateOptimizationStats() {
        let extPts = rawPoints.filter { $0.isExtrusion }
        var layersOpt: [Int: [simd_float3]] = [:]
        for point in extPts { let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y)); layersOpt[point.layer, default: []].append(pos) }
        var originalCount = 0, optimizedCount = 0
        for (_, var points) in layersOpt { originalCount += points.count; removeCollinearPoints(from: &points, angleThresholdDeg: 5.0); optimizedCount += points.count }
        DispatchQueue.main.async {
            self.stats?.originalExtrusionPoints = originalCount
            self.stats?.optimizedExtrusionPoints = optimizedCount
            self.stats?.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
        }
    }
    
    private func createTubeBuffers(for path: [simd_float3], radius: Float, segments: Int) -> (v: [SCNVector3], n: [SCNVector3], i: [Int32])? {
        let pointCount = path.count
        if pointCount < 2 { return nil }
        var vertices: [SCNVector3] = []; var normals: [SCNVector3] = []; var indices: [Int32] = []
        vertices.reserveCapacity(pointCount * segments); normals.reserveCapacity(pointCount * segments); indices.reserveCapacity(pointCount * segments * 6)
        var T = simd_normalize(path[1] - path[0]); var N = simd_float3(0, 1, 0)
        if abs(simd_dot(T, N)) > 0.99 { N = simd_float3(1, 0, 0) }
        N = simd_normalize(simd_cross(T, N)); var B = simd_cross(T, N)
        for i in 0..<pointCount {
            if i > 0 {
                let newT = simd_normalize(path[i] - path[i-1]); let axis = simd_cross(T, newT); let len = simd_length(axis)
                if len > 0.0001 { let angle = acos(min(max(simd_dot(T, newT), -1.0), 1.0)); let q = simd_quatf(angle: angle, axis: axis / len); N = q.act(N); B = q.act(B) }
                T = newT
            }
            for j in 0..<segments {
                let angle = Float(j) / Float(segments) * Float.pi * 2; let cosA = cos(angle); let sinA = sin(angle)
                let normal = simd_normalize(N * cosA + B * sinA); let pos = path[i] + normal * radius
                normals.append(SCNVector3(normal)); vertices.append(SCNVector3(pos))
            }
        }
        for i in 0..<pointCount - 1 {
            let idx1 = Int32(i * segments); let idx2 = Int32((i + 1) * segments)
            for j in 0..<segments {
                let curr1 = idx1 + Int32(j); let next1 = idx1 + (Int32(j) + 1) % Int32(segments)
                let curr2 = idx2 + Int32(j); let next2 = idx2 + (Int32(j) + 1) % Int32(segments)
                indices.append(contentsOf: [curr1, next1, curr2, next1, next2, curr2])
            }
        }
        return (vertices, normals, indices)
    }
}

func removeCollinearPoints(from points: inout [simd_float3], angleThresholdDeg: Float) {
    guard points.count > 2 else { return }
    var filtered: [simd_float3] = [points[0]]
    for i in 1..<points.count - 1 {
        let p1 = filtered.last!; let p2 = points[i]; let p3 = points[i + 1]
        let v1 = p2 - p1; let v2 = p3 - p2; let len1 = simd_length(v1); let len2 = simd_length(v2)
        if len1 < 0.001 || len2 < 0.001 { continue }
        let dot = simd_dot(v1 / len1, v2 / len2)
        let angle = acos(min(max(dot, -1.0), 1.0)) * (180.0 / Float.pi)
        if angle > angleThresholdDeg { filtered.append(p2) }
    }
    filtered.append(points.last!); points = filtered
}

extension Color {
    init?(hex: String) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines); hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")
        var rgb: UInt64 = 0; Scanner(string: hexSanitized).scanHexInt64(&rgb)
        self.init(red: Double((rgb & 0xFF0000) >> 16) / 255.0, green: Double((rgb & 0x00FF00) >> 8) / 255.0, blue: Double(rgb & 0x0000FF) / 255.0)
    }
}
