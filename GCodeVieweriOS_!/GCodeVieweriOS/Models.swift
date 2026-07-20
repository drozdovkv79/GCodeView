import Foundation
import simd
import SwiftUI
import Combine
import SceneKit
import ReplayKit
import Photos

struct GCodePoint { var x: Float = 0; var y: Float = 0; var z: Float = 0; var e: Float = 0; var feedRate: Float = 0; var layer: Int = 0; var isExtrusion: Bool = false }

struct GCodeStats {
    var totalPoints: Int = 0; var extrusionPoints: Int = 0; var travelPoints: Int = 0
    var width: Float = 0; var length: Float = 0; var height: Float = 0
    var numLayers: Int = 0; var totalMaterial: Float = 0; var volume: Float = 0
    var maxZ: Float = 0; var maxSpeed: Float = 0
    var originalExtrusionPoints: Int = 0; var optimizedExtrusionPoints: Int = 0; var optimizationReductionPercent: Double = 0
    var centerOfMassX: Float = 0
    var centerOfMassY: Float = 0
    var boundingBoxVolume: Float = 0
    var xyFootprintArea: Float = 0
    var modelCompactness: Float = 0
}

enum CameraAction { case none, front, back, top, bottom, left, right, iso1, iso2, iso3, iso4, rotate360 }
enum MaterialPreset: String, CaseIterable { case plastic = "Пластик"; case steel = "Металл"; case glass = "Стекло" }

struct LayerMesh { let id: Int; let vertices: [SCNVector3]; let normals: [SCNVector3]; let indices: [Int32] }

private struct AssociatedKeys {
    static var previewDelegate = "previewDelegate"
}

class AppState: ObservableObject {
    @Published var rawPoints: [GCodePoint] = []
    @Published var stats: GCodeStats?
    @Published var isLoading: Bool = false
    @Published var isCalculatingAnalytics: Bool = false
    @Published var progress: Double = 0
    @Published var logMessages: [String] = []
    
    @Published var tubeDiameter: Float = 4.0
    @Published var lastAppliedDiameter: Float = 4.0
    @Published var modelColor: Color = Color(hex: "#e9e5ce")!
    @Published var renderTrigger: Int = 0
    
    @Published var cameraAction: CameraAction = .none
    @Published var selectedMaterial: MaterialPreset = .plastic
    @Published var isRecording: Bool = false
    
    @Published var processedLayers: [LayerMesh] = []
    @Published var modelBoundingBox: (min: simd_float3, max: simd_float3)? = nil
    @Published var modelSize: simd_float3 = simd_float3(1,1,1)
    
    @Published var selectedFileURL: URL? = nil
    @Published var isAccessingSecurityScopedResource: Bool = false
    
    func log(_ message: String) {
        DispatchQueue.main.async {
            let time = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
            self.logMessages.append("[\(time)] \(message)")
        }
    }
    
    func loadSelectedFile() {
        guard let file = selectedFileURL else { return }
        isLoading = true
        stats = nil
        log("📂 Start loading: \(file.lastPathComponent)")
        
        DispatchQueue.global(qos: .userInitiated).async {
            let points = GCodeParser.parse(file: file) { progress in
                DispatchQueue.main.async { self.progress = progress }
            }
            
            DispatchQueue.main.async {
                self.rawPoints = points
                self.log("📊 Points extracted: \(points.count)")
                DispatchQueue.global(qos: .userInitiated).async {
                    self.processGeometry()
                }
            }
        }
    }
    
    func calculateAnalytics() {
        guard !rawPoints.isEmpty else { return }
        isCalculatingAnalytics = true
        log("📊 Calculating analytics...")
        
        DispatchQueue.global(qos: .userInitiated).async {
            var stats = GCodeStats()
            var extMinX: Float = .greatestFiniteMagnitude, extMaxX: Float = -.greatestFiniteMagnitude
            var extMinY: Float = .greatestFiniteMagnitude, extMaxY: Float = -.greatestFiniteMagnitude
            var extMinZ: Float = .greatestFiniteMagnitude, extMaxZ: Float = -.greatestFiniteMagnitude
            var totalE: Float = 0
            var maxSpeed: Float = 0
            
            var layersOpt: [Int: [simd_float3]] = [:]
            
            for point in self.rawPoints {
                stats.totalPoints += 1
                if point.isExtrusion {
                    stats.extrusionPoints += 1
                    if point.x < extMinX { extMinX = point.x }; if point.x > extMaxX { extMaxX = point.x }
                    if point.y < extMinY { extMinY = point.y }; if point.y > extMaxY { extMaxY = point.y }
                    if point.z < extMinZ { extMinZ = point.z }; if point.z > extMaxZ { extMaxZ = point.z }
                    totalE += point.e
                    if point.feedRate > maxSpeed { maxSpeed = point.feedRate }
                    
                    let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
                    layersOpt[point.layer, default: []].append(pos)
                } else {
                    stats.travelPoints += 1
                }
            }
            
            stats.width = extMaxX - extMinX; stats.length = extMaxY - extMinY; stats.height = extMaxZ - extMinZ
            stats.maxZ = extMaxZ; stats.centerOfMassX = extMinX + stats.width / 2.0; stats.centerOfMassY = extMinY + stats.length / 2.0
            stats.numLayers = (self.rawPoints.map { $0.layer }.max() ?? 0) + 1
            stats.totalMaterial = totalE
            let filamentArea = Float.pi * Float.pi * 0.765625
            stats.volume = totalE * filamentArea
            stats.maxSpeed = maxSpeed
            stats.boundingBoxVolume = stats.width * stats.length * stats.height
            stats.xyFootprintArea = stats.width * stats.length
            
            var originalCount = 0, optimizedCount = 0
            for (_, var points) in layersOpt {
                originalCount += points.count
                removeCollinearPoints(from: &points, angleThresholdDeg: 5.0)
                optimizedCount += points.count
            }
            stats.originalExtrusionPoints = originalCount
            stats.optimizedExtrusionPoints = optimizedCount
            stats.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
            
            DispatchQueue.main.async {
                self.stats = stats
                self.isCalculatingAnalytics = false
                self.log("✅ Analytics calculated")
            }
        }
    }
    
    func applyDiameter() {
        lastAppliedDiameter = tubeDiameter
        log("Диаметр изменен. Пересчет геометрии...")
        DispatchQueue.global(qos: .userInitiated).async {
            self.processGeometry()
        }
    }
    
    func applyMaterial() {
        renderTrigger += 1
        log("Материал изменен на \(selectedMaterial.rawValue)")
    }
    
    func recordVideo() {
        guard !rawPoints.isEmpty else { return }
        
        let recorder = RPScreenRecorder.shared()
        
        if recorder.isRecording {
            // ОСТАНОВКА ЗАПИСИ
            isRecording = false
            log("Остановка записи...")
            
            recorder.stopRecording { previewViewController, error in
                if let error = error {
                    DispatchQueue.main.async { self.log("Ошибка остановки: \(error.localizedDescription)") }
                    return
                }
                
                guard let preview = previewViewController else {
                    DispatchQueue.main.async { self.log("Не удалось создать превью") }
                    return
                }
                
                // Назначаем делегат, чтобы окно закрывалось после сохранения
                let previewDelegate = PreviewDelegate()
                // Сохраняем делегат в ассоциированные объекты, чтобы он не удалился из памяти
                objc_setAssociatedObject(preview, &AssociatedKeys.previewDelegate, previewDelegate, .OBJC_ASSOCIATION_RETAIN)
                preview.previewControllerDelegate = previewDelegate
                
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                       let window = windowScene.windows.first,
                       var topController = window.rootViewController {
                        
                        while let presented = topController.presentedViewController {
                            topController = presented
                        }
                        
                        topController.present(preview, animated: true)
                        self.log("Открыто окно предпросмотра")
                    }
                }
            }
            return
        }
        
        // НАЧАЛО ЗАПИСИ
        log("🎬 Запись экрана...")
        isRecording = true
        
        recorder.startRecording { error in
            if let error = error {
                DispatchQueue.main.async {
                    self.isRecording = false
                    self.log("Ошибка записи: \(error.localizedDescription)")
                }
                return
            }
            
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                   let window = windowScene.windows.first,
                   let scnView = self.findSCNView(in: window) {
                    if let rootNode = scnView.scene?.rootNode.childNode(withName: "gcode", recursively: false) {
                        let action = SCNAction.rotateBy(x: 0, y: CGFloat(Float.pi * 2), z: 0, duration: 3.0)
                        rootNode.runAction(action)
                    }
                }
            }
            
            DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) {
                if self.isRecording {
                    self.recordVideo()
                }
            }
        }
    }
    
    private func findSCNView(in view: UIView) -> SCNView? {
        if let scnView = view as? SCNView { return scnView }
        for subview in view.subviews {
            if let found = findSCNView(in: subview) { return found }
        }
        return nil
    }
    
    private func processGeometry() {
        let extPts = rawPoints.filter { $0.isExtrusion }
        let radius = Float(tubeDiameter / 2.0)
        let segments = 6
        
        var layers: [Int: [simd_float3]] = [:]
        var globalMin = simd_float3(repeating: Float.greatestFiniteMagnitude)
        var globalMax = simd_float3(repeating: -Float.greatestFiniteMagnitude)
        
        for point in extPts {
            let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
            layers[point.layer, default: []].append(pos)
            globalMin = simd_min(globalMin, pos)
            globalMax = simd_max(globalMax, pos)
        }
        
        var meshes: [LayerMesh] = []
        
        for (layerIndex, var points) in layers.sorted(by: { $0.key < $1.key }) {
            if points.count < 2 { continue }
            
            if points.count > 500 {
                let step = points.count / 500
                points = stride(from: 0, to: points.count, by: step).map { points[$0] }
            } else {
                removeCollinearPoints(from: &points, angleThresholdDeg: 5.0)
            }
            
            if points.count < 2 { continue }
            
            if let tubeData = createTubeBuffers(for: points, radius: radius, segments: segments) {
                meshes.append(LayerMesh(id: layerIndex, vertices: tubeData.v, normals: tubeData.n, indices: tubeData.i))
            }
        }
        
        DispatchQueue.main.async {
            self.processedLayers = meshes
            self.modelBoundingBox = (globalMin, globalMax)
            self.modelSize = globalMax - globalMin
            self.isLoading = false
            self.renderTrigger += 1
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

class PreviewDelegate: NSObject, RPPreviewViewControllerDelegate {
    func previewControllerDidFinish(_ previewController: RPPreviewViewController) {
        previewController.dismiss(animated: true)
    }
    
    func previewController(_ previewController: RPPreviewViewController, didFinishWithActivityTypes activityTypes: Set<UIActivity.ActivityType>) {
        previewController.dismiss(animated: true)
    }
}
