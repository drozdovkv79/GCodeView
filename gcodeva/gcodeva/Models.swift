import Foundation
import simd
import SwiftUI
import Combine
import SceneKit
import UniformTypeIdentifiers

struct GCodePoint { var x: Float = 0; var y: Float = 0; var z: Float = 0; var e: Float = 0; var feedRate: Float = 0; var layer: Int = 0; var isExtrusion: Bool = false }

struct TempChange: Identifiable {
    let id = UUID()
    let layer: Int
    let z: Float
    let temp: Float
    let command: String
}

struct GCodeStats {
    var fileName: String = ""
    var fileSize: Int64 = 0
    var width: Float = 0; var length: Float = 0; var height: Float = 0
    var originalExtrusionPoints: Int = 0;
    var optimizedExtrusionPoints: Int = 0;
    var optimizationReductionPercent: Double = 0
    var extrusionPoints: Int = 0
    var extrusionPathLength: Float = 0
    var maxSpeedMmPerMin: Float = 0
    var minLayerSpeedMmPerMin: Float = 0  // 🆕 Минимальная скорость слоя
    var avgLayerSpeedMmPerMin: Float = 0  // 🆕 Средняя скорость слоев
    var maxLayerSpeedMmPerMin: Float = 0  // 🆕 Максимальная скорость слоя
    var minLayerTimeSec: Float = 0  // 🆕 Минимальное время слоя (сек)
    var avgLayerTimeSec: Float = 0  // 🆕 Среднее время слоя (сек)
    var maxLayerTimeSec: Float = 0  // 🆕 Максимальное время слоя (сек)
    var estimatedPrintTimeMin: Float = 0
    var numLayers: Int = 0
    var totalExtrusion: Float = 0
    var minEPerPoint: Float = 0
    var maxEPerPoint: Float = 0
    var minEPointCoords: String = ""
    var maxEPointCoords: String = ""
    var tempChanges: [TempChange] = []
    var totalPoints: Int = 0; var travelPoints: Int = 0
    var lengthBottom: Float = 0
    var lengthTop: Float = 0
    var temperatures: [String: Float] = [:]
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

// НОВАЯ СТРУКТУРА ДЛЯ ЗАГРУЖЕННЫХ МОДЕЛЕЙ
struct LoadedModel: Identifiable {
    let id = UUID()
    var name: String
    let fileURL: URL
    var points: [GCodePoint] = []
    var processedLayers: [LayerMesh] = []
    var position: simd_float3 = simd_float3(0, 0, 0)
    var boundingBox: (min: simd_float3, max: simd_float3)? = nil
    var modelSize: simd_float3 = simd_float3(1, 1, 1)
    var isVisible: Bool = true
    var rotationY: Float = 0 // 🆕 Текущий поворот вокруг оси Y
    var originalExtrusionPoints: Int = 0
    var optimizedExtrusionPoints: Int = 0
    var optimizationReductionPercent: Double = 0
}

class AppState: ObservableObject {
    @Published var fileItems: [FileItem] = []
    @Published var sortOrder: SortOrder = .name
    @Published var currentDirectory: URL?
    @Published var selectedFileURL: URL?
    @Published var rawPoints: [GCodePoint] = []
    @Published var stats: GCodeStats?
    @Published var isLoading: Bool = false
    @Published var isCalculatingAnalytics: Bool = false
    @Published var progress: Double = 0
    @Published var logMessages: [String] = []
    
    // НОВЫЕ СВОЙСТВА ДЛЯ УПРАВЛЕНИЯ НЕСКОЛЬКИМИ МОДЕЛЯМИ
    @Published var loadedModels: [LoadedModel] = []
    @Published var selectedModelID: UUID? = nil
    @Published var newModelPositionX: Float = 0
    @Published var newModelPositionY: Float = 0
    @Published var newModelPositionZ: Float = 0
    
    @Published var tempTubeDiameter: Float = 6.0
    @Published var tempModelColor: Color = Color(hex: "#e9e5ce")!
    @Published var tubeDiameter: Float = 6.0
    @Published var modelColor: Color = Color(hex: "#e9e5ce")!
    @Published var renderTrigger: Int = 0
    @Published var lightingTrigger: Int = 0
    @Published var tempCollinearAngle: Float = 5.0
    @Published var collinearAngle: Float = 5.0
    
    @Published var cameraAction: CameraAction = .none
    @Published var selectedMaterial: MaterialPreset = .matte
    @Published var isRecording: Bool = false
    @Published var videoWidth: Int = 738
    @Published var videoHeight: Int = 1600
    @Published var showAxis: Bool = true
    @Published var modelSize: simd_float3 = simd_float3(1,1,1)
    @Published var shouldResetCamera = false
    @Published var parsedTemperatures: [String: Float] = [:]
    
    // MARK: - 🆕 Измерение расстояний
    @Published var isMeasuringMode: Bool = false
    @Published var measurePoints: [simd_float3] = []
    @Published var measureSnapAxis: String = "None"
    @Published var measureDistance: String = ""
    
    // MARK: - Освещение
    @Published var lightingPreset: LightingPreset = .relief
    @Published var lightingAmbient: Float = 0.10
    @Published var lightingMainIntensity: Float = 1.60
    @Published var lightingAngleH: Float = 0
    @Published var lightingAngleV: Float = 6
    @Published var lightingFillIntensity: Float = 0.25
    @Published var simplifyEpsilon: Float = 0.0
    
    @Published var processedLayers: [LayerMesh] = []
    @Published var modelBoundingBox: (min: simd_float3, max: simd_float3)? = nil
    
    weak var sceneView: SCNView?
    
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
        stats = nil
        
        log("📂 Start loading: \(file.lastPathComponent)")
        
        DispatchQueue.global(qos: .userInitiated).async {
            let parseStartTime = CFAbsoluteTimeGetCurrent()
            
            let result = GCodeParser.parse(file: file) { progress in
                DispatchQueue.main.async { self.progress = progress }
            }
            let points = result.points
            let temperatures = result.temperatures
            
            let parseEndTime = CFAbsoluteTimeGetCurrent()
            let parseMs = (parseEndTime - parseStartTime) * 1000
            
            var model = LoadedModel(
                name: file.lastPathComponent,
                fileURL: file,
                points: points,
                position: simd_float3(0, 0, 0)
            )
            
            self.processGeometryForModel(&model)
            
            DispatchQueue.main.async {
                self.log("⏱ Total Parse Time: \(String(format: "%.0f", parseMs)) ms")
                self.log("📊 Points extracted: \(points.count)")
                self.log("🌡️ Temperatures found: \(temperatures.count)")
                
                self.parsedTemperatures = temperatures
                
                self.loadedModels.removeAll()
                self.loadedModels.append(model)
                self.selectedModelID = model.id
                
                self.rawPoints = points
                self.tubeDiameter = self.tempTubeDiameter
                self.modelColor = self.tempModelColor
                self.renderTrigger += 1
                
                self.calculateAnalytics()
                
                self.isLoading = false
                self.cameraAction = .front
            }
        }
    }

    func addModel() {
        guard let file = selectedFileURL else {
            log("⚠️ No file selected. Please select a file from the list first.")
            return
        }
        
        // 🆕 УБРАНА проверка на дубликат. Теперь можно добавлять один и тот же файл много раз.
        
        log("📂 Adding model from list: \(file.lastPathComponent)")
        isLoading = true
        
        DispatchQueue.global(qos: .userInitiated).async {
            let result = GCodeParser.parse(file: file) { progress in
                DispatchQueue.main.async { self.progress = progress }
            }
            let points = result.points
            let temperatures = result.temperatures
            
            var newPos = simd_float3(self.newModelPositionX, self.newModelPositionY, self.newModelPositionZ)
            
            if newPos.x == 0 && newPos.y == 0 && newPos.z == 0 && !self.loadedModels.isEmpty {
                var maxX: Float = 0
                for model in self.loadedModels {
                    if let bbox = model.boundingBox {
                        let modelWidth = bbox.max.x - bbox.min.x
                        let modelRightEdge = model.position.x + modelWidth / 2
                        if modelRightEdge > maxX {
                            maxX = modelRightEdge
                        }
                    }
                }
                newPos.x = maxX + 50
            }
            
            var model = LoadedModel(
                name: file.lastPathComponent,
                fileURL: file,
                points: points,
                position: newPos
            )
            
            // 🆕 Формируем короткий ID и приклеиваем его к имени
            let shortId = String(model.id.uuidString.prefix(8))
            model.name = "\(file.lastPathComponent) [\(shortId)]"
            
            self.processGeometryForModel(&model)
            
            DispatchQueue.main.async {
                if self.loadedModels.isEmpty {
                    self.parsedTemperatures = temperatures
                } else {
                    for (key, value) in temperatures {
                        self.parsedTemperatures[key] = value
                    }
                }
                
                self.loadedModels.append(model)
                self.selectedModelID = model.id
                self.isLoading = false
                self.renderTrigger += 1
                self.log("✅ Model added: \(model.name)")
                self.log("📍 Position: X=\(model.position.x), Y=\(model.position.y), Z=\(model.position.z)")
            }
        }
    }
    
    func processGeometryForModel(_ model: inout LoadedModel) {
        let radius = Float(tubeDiameter / 2.0)
        let segments = 8
        
        let angles: [(cos: Float, sin: Float)] = (0..<segments).map { j in
            let angle = Float(j) / Float(segments) * Float.pi * 2
            return (cos(angle), sin(angle))
        }
        
        let extrusionPoints = model.points.filter { $0.isExtrusion }
        guard !extrusionPoints.isEmpty else { return }
        
        let groupedByLayer = Dictionary(grouping: extrusionPoints) { $0.layer }
        
        let layerKeys = groupedByLayer.keys.sorted()
        let layerCount = layerKeys.count
        
        var meshes: [Int: LayerMesh] = [:]
        let lock = NSLock()
        
        DispatchQueue.concurrentPerform(iterations: layerCount) { index in
            let layerID = layerKeys[index]
            let layerPoints = groupedByLayer[layerID]!
            
            var positions = layerPoints.map { simd_float3(Float($0.x), Float($0.z), -Float($0.y)) }
            
            if collinearAngle > 0 {
                removeCollinearPointsOptimized(&positions, angleThresholdDeg: collinearAngle)
            }
            
            if positions.count >= 2 {
                if let tubeData = createTubeBuffersOptimized(for: positions,
                                                             radius: radius,
                                                             segments: segments,
                                                             precomputedAngles: angles) {
                    let mesh = LayerMesh(id: layerID,
                                         vertices: tubeData.v,
                                         normals: tubeData.n,
                                         indices: tubeData.i)
                    lock.lock()
                    meshes[layerID] = mesh
                    lock.unlock()
                }
            }
        }
        
        let sortedMeshes = layerKeys.compactMap { meshes[$0] }
        
        model.processedLayers = sortedMeshes
        if let firstPoint = extrusionPoints.first {
            var globalMin = simd_float3(Float(firstPoint.x), Float(firstPoint.z), -Float(firstPoint.y))
            var globalMax = globalMin
            
            for point in extrusionPoints {
                let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
                globalMin = simd_min(globalMin, pos)
                globalMax = simd_max(globalMax, pos)
            }
            model.boundingBox = (globalMin, globalMax)
            model.modelSize = globalMax - globalMin
        }
        
        let originalCount = extrusionPoints.count
        let optimizedCount = model.processedLayers.reduce(0) { $0 + $1.vertices.count / 8 }
        model.originalExtrusionPoints = originalCount
        model.optimizedExtrusionPoints = optimizedCount
        model.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
    }
    
    func removeCollinearPointsOptimized(_ points: inout [simd_float3], angleThresholdDeg: Float) {
        let count = points.count
        guard count > 2 else { return }
        
        let cosThreshold = cos(angleThresholdDeg * Float.pi / 180)
        let cosThresholdSq = cosThreshold * cosThreshold
        
        var keep = [Bool](repeating: false, count: count)
        keep[0] = true
        keep[count - 1] = true
        
        var lastKept = 0
        
        for i in 1..<count-1 {
            let p1 = points[lastKept]
            let p2 = points[i]
            let p3 = points[i + 1]
            
            let v1 = p2 - p1
            let v2 = p3 - p2
            
            let len1Sq = simd_length_squared(v1)
            let len2Sq = simd_length_squared(v2)
            
            if len1Sq < 1e-6 || len2Sq < 1e-6 {
                continue
            }
            
            let dotProduct = simd_dot(v1, v2)
            
            if dotProduct < 0 {
                keep[i] = true
                lastKept = i
                continue
            }
            
            let dotSq = dotProduct * dotProduct
            if dotSq < cosThresholdSq * len1Sq * len2Sq {
                keep[i] = true
                lastKept = i
            }
        }
        
        var newPoints = [simd_float3]()
        newPoints.reserveCapacity(count)
        for i in 0..<count where keep[i] {
            newPoints.append(points[i])
        }
        points = newPoints
    }
    
    func processGeometryForModel0(_ model: inout LoadedModel) {
        let radius = Float(tubeDiameter / 2.0)
        let segments = 8
        
        let angles: [(cos: Float, sin: Float)] = (0..<segments).map { j in
            let angle = Float(j) / Float(segments) * Float.pi * 2
            return (cos(angle), sin(angle))
        }
        
        var layers: [Int: [simd_float3]] = [:]
        var globalMin = simd_float3(repeating: Float.greatestFiniteMagnitude)
        var globalMax = simd_float3(repeating: -Float.greatestFiniteMagnitude)
        
        for point in model.points {
            guard point.isExtrusion else { continue }
            let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
            layers[point.layer, default: []].append(pos)
            globalMin = simd_min(globalMin, pos)
            globalMax = simd_max(globalMax, pos)
        }
        
        let sortedLayers = layers.sorted { $0.key < $1.key }
        let layerCount = sortedLayers.count
        
        var meshes: [LayerMesh?] = Array(repeating: nil, count: layerCount)
        var originalCount = 0
        var optimizedCount = 0
        
        DispatchQueue.concurrentPerform(iterations: layerCount) { index in
            var (layerID, points) = sortedLayers[index]
            originalCount += points.count
            removeCollinearPoints(from: &points, angleThresholdDeg: self.collinearAngle)
            optimizedCount += points.count
            if let tubeData = self.createTubeBuffersOptimized(for: points, radius: radius, segments: segments, precomputedAngles: angles) {
                let mesh = LayerMesh(id: layerID, vertices: tubeData.v, normals: tubeData.n, indices: tubeData.i)
                meshes[index] = mesh
            }
        }
        
        model.processedLayers = meshes.compactMap { $0 }
        model.boundingBox = (globalMin, globalMax)
        model.modelSize = globalMax - globalMin
        model.originalExtrusionPoints = originalCount
        model.optimizedExtrusionPoints = optimizedCount
        model.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
    }
    
    func removeModel(withID id: UUID) {
        if let index = loadedModels.firstIndex(where: { $0.id == id }) {
            let modelName = loadedModels[index].name
            loadedModels.remove(at: index)
            log("🗑️ Model removed: \(modelName)")
            if selectedModelID == id {
                selectedModelID = loadedModels.first?.id
            }
            renderTrigger += 1
        }
    }
    
    func updateModelPosition(modelID: UUID, x: Float, y: Float, z: Float) {
        if let index = loadedModels.firstIndex(where: { $0.id == modelID }) {
            loadedModels[index].position = simd_float3(x, y, z)
            log("📍 Model moved: \(loadedModels[index].name) to X=\(x), Y=\(y), Z=\(z)")
            renderTrigger += 1
        }
    }
    
    // MARK: - 🆕 Поворот модели
    func rotateModel180(modelID: UUID) {
        if let index = loadedModels.firstIndex(where: { $0.id == modelID }) {
            loadedModels[index].rotationY += Float.pi
            log("🔄 Model rotated 180°: \(loadedModels[index].name)")
            renderTrigger += 1
        }
    }
    
    func resetModelRotation(modelID: UUID) {
        if let index = loadedModels.firstIndex(where: { $0.id == modelID }) {
            loadedModels[index].rotationY = 0
            renderTrigger += 1
        }
    }
    
    func toggleModelVisibility(modelID: UUID) {
        if let index = loadedModels.firstIndex(where: { $0.id == modelID }) {
            loadedModels[index].isVisible.toggle()
            log("👁️ Model visibility: \(loadedModels[index].name) -> \(loadedModels[index].isVisible ? "visible" : "hidden")")
            renderTrigger += 1
        }
    }
    
    func calculateAnalytics() {
        guard let currentModel = loadedModels.first else {
            log("⚠️ No model loaded to calculate analytics")
            isCalculatingAnalytics = false
            return
        }
        
        isCalculatingAnalytics = true
        log("📊 Calculating analytics for: \(currentModel.name)")
        let startTime = CFAbsoluteTimeGetCurrent()
        
        DispatchQueue.global(qos: .userInitiated).async {
            let points = currentModel.points
            let url = currentModel.fileURL
            
            var stats = GCodeStats()
            stats.fileName = url.lastPathComponent
            stats.fileSize = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int64) ?? 0
            
            var minX = Float.greatestFiniteMagnitude
            var maxX = -Float.greatestFiniteMagnitude
            var minY = minX, maxY = maxX
            var minZ = minX, maxZ = maxX
            
            var extPath: Float = 0
            var printTime: Float = 0
            var maxF: Float = 0
            var extCount = 0
            var totalE: Float = 0
            var lastE: Float = 0
            var lastPoint: GCodePoint?
            
            var zLevelYBounds: [Float: (minY: Float, maxY: Float)] = [:]
            var uniqueLayers = Set<Int>()
            
            // 🆕 Словарь для накопления скоростей экструзии по каждому слою
            var layerSpeedAccumulator: [Int: (totalSpeed: Float, count: Int)] = [:]
            // 🆕 Словарь для накопления времени печати по каждому слою (в секундах)
            var layerTimeAccumulator: [Int: Float] = [:]
            
            // --- ЕДИНСТВЕННЫЙ ПРОХОД ПО ТОЧКАМ ---
            
            // 🆕 Отслеживаем реальную высоту для определения смены слоя
            var lastZHeight: Float = -.greatestFiniteMagnitude
            var currentValidLayer: Int = 0
            
            for point in points {
                // Слой меняется ТОЛЬКО если высота (point.z) изменилась более чем на 1 мм
                if abs(point.z - lastZHeight) >= 3 {
                    currentValidLayer += 1
                    lastZHeight = point.z
                }
                
                // Добавляем в набор только валидные слои
                uniqueLayers.insert(currentValidLayer)
                
                if point.isExtrusion {
                    extCount += 1
                    minX = min(minX, point.x)
                    maxX = max(maxX, point.x)
                    minY = min(minY, point.y)
                    maxY = max(maxY, point.y)
                    minZ = min(minZ, point.z)
                    maxZ = max(maxZ, point.z)
                    maxF = max(maxF, point.feedRate)
                    
                    // Накапливаем скорость строго для валидных слоев
                    if point.feedRate > 0 {
                        var acc = layerSpeedAccumulator[currentValidLayer, default: (0.0, 0)]
                        acc.totalSpeed += point.feedRate
                        acc.count += 1
                        layerSpeedAccumulator[currentValidLayer] = acc
                    }
                    
                    let deltaE = point.e - lastE
                    if deltaE > 0 {
                        totalE += deltaE
                    }
                    lastE = point.e
                    
                    // Обновляем границы Y для текущего уровня Z
                    var bounds = zLevelYBounds[point.z, default: (.greatestFiniteMagnitude, -.greatestFiniteMagnitude)]
                    bounds.minY = min(bounds.minY, point.y)
                    bounds.maxY = max(bounds.maxY, point.y)
                    zLevelYBounds[point.z] = bounds
                }
                
                if let prev = lastPoint {
                    let dx = point.x - prev.x
                    let dy = point.y - prev.y
                    let dz = point.z - prev.z
                    let distSq = dx*dx + dy*dy + dz*dz
                    
                    if distSq > 0.000001 {
                        let dist = sqrt(distSq)
                        if point.isExtrusion {
                            extPath += dist
                            // Накапливаем время печати строго для валидных слоев
                            let speed = point.feedRate > 0 ? point.feedRate : 1000.0
                            layerTimeAccumulator[currentValidLayer, default: 0.0] += (dist / speed) * 60.0
                        }
                        let speed = point.feedRate > 0 ? point.feedRate : 1000.0
                        printTime += dist / speed
                    }
                }
                lastPoint = point
            }
            
            if let bottomBounds = zLevelYBounds[minZ] { stats.lengthBottom = bottomBounds.maxY - bottomBounds.minY }
            if let topBounds = zLevelYBounds[maxZ] { stats.lengthTop = topBounds.maxY - topBounds.minY }
            
            stats.width = maxX - minX
            stats.length = maxY - minY
            stats.height = maxZ - minZ
            stats.extrusionPoints = extCount
            stats.extrusionPathLength = extPath
            stats.maxSpeedMmPerMin = maxF
            
            // 🆕 Расчет минимальной, средней и максимальной скорости слоев
            if !layerSpeedAccumulator.isEmpty {
                var layerAvgs: [Float] = []
                layerAvgs.reserveCapacity(layerSpeedAccumulator.count)
                
                for (_, acc) in layerSpeedAccumulator {
                    if acc.count > 0 {
                        layerAvgs.append(acc.totalSpeed / Float(acc.count))
                    }
                }
                
                if !layerAvgs.isEmpty {
                    stats.minLayerSpeedMmPerMin = layerAvgs.min() ?? 0
                    stats.maxLayerSpeedMmPerMin = layerAvgs.max() ?? 0
                    let sum = layerAvgs.reduce(0.0, +)
                    stats.avgLayerSpeedMmPerMin = sum / Float(layerAvgs.count)
                }
            }
            
            // 🆕 Расчет минимального, среднего и максимального времени печати слоев
            if !layerTimeAccumulator.isEmpty {
                let layerTimes = Array(layerTimeAccumulator.values)
                stats.minLayerTimeSec = layerTimes.min() ?? 0
                stats.maxLayerTimeSec = layerTimes.max() ?? 0
                let sumTime = layerTimes.reduce(0.0, +)
                stats.avgLayerTimeSec = sumTime / Float(layerTimes.count)
            }

            stats.estimatedPrintTimeMin = printTime
            stats.numLayers = uniqueLayers.count
            stats.totalExtrusion = totalE
            stats.originalExtrusionPoints = currentModel.originalExtrusionPoints
            stats.optimizedExtrusionPoints = currentModel.optimizedExtrusionPoints
            stats.optimizationReductionPercent = currentModel.optimizationReductionPercent
            
            let endTime = CFAbsoluteTimeGetCurrent()
            
            DispatchQueue.main.async {
                self.stats = stats
                self.isCalculatingAnalytics = false
                self.log("⏱ Analytics calculated in \(String(format: "%.2f", (endTime - startTime) * 1000)) ms")
            }
        }
    }
    
    private func extractFloatFromData(data: Data.SubSequence, targetChar: UInt8) -> Float? {
        guard let targetIndex = data.firstIndex(of: targetChar) else { return nil }
        
        var index = data.index(after: targetIndex)
        var isNegative = false
        var hasDot = false
        var result: Float = 0
        var decimalMultiplier: Float = 1
        
        if index < data.endIndex && data[index] == 45 {
            isNegative = true
            index = data.index(after: index)
        }
        
        while index < data.endIndex {
            let byte = data[index]
            if byte >= 48 && byte <= 57 {
                let digit = Float(byte - 48)
                if hasDot {
                    decimalMultiplier *= 0.1
                    result += digit * decimalMultiplier
                } else {
                    result = result * 10 + digit
                }
            } else if byte == 46 && !hasDot {
                hasDot = true
            } else {
                break
            }
            index = data.index(after: index)
        }
        
        return isNegative ? -result : result
    }
    
    private func processGeometry0() {
        let startTime = CFAbsoluteTimeGetCurrent()
        
        let radius = Float(tubeDiameter / 2.0)
        let segments = 8
        
        let angles: [(cos: Float, sin: Float)] = (0..<segments).map { j in
            let angle = Float(j) / Float(segments) * Float.pi * 2
            return (cos(angle), sin(angle))
        }
        
        var layers: [Int: [simd_float3]] = [:]
        var globalMin = simd_float3(repeating: Float.greatestFiniteMagnitude)
        var globalMax = simd_float3(repeating: -Float.greatestFiniteMagnitude)
        
        layers.reserveCapacity(3000)
        for point in rawPoints {
            guard point.isExtrusion else { continue }
            let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
            layers[point.layer, default: []].append(pos)
            globalMin = simd_min(globalMin, pos)
            globalMax = simd_max(globalMax, pos)
        }
        
        let sortedLayers = layers.sorted { $0.key < $1.key }
        let layerCount = sortedLayers.count
        
        var meshes: [LayerMesh?] = Array(repeating: nil, count: layerCount)
        
        var originalCount = 0
        var optimizedCount = 0
        DispatchQueue.concurrentPerform(iterations: layerCount) { index in
            var (layerID, points) = sortedLayers[index]
            originalCount+=points.count
            removeCollinearPoints(from: &points, angleThresholdDeg: collinearAngle)
            optimizedCount+=points.count
            if let tubeData = createTubeBuffersOptimized(for: points,
                                                         radius: radius,
                                                         segments: segments,
                                                         precomputedAngles: angles) {
                let mesh = LayerMesh(id: layerID,
                                     vertices: tubeData.v,
                                     normals: tubeData.n,
                                     indices: tubeData.i)
                meshes[index] = mesh
            }
        }
        
        if var vstats = self.stats {
            vstats.originalExtrusionPoints = originalCount
            vstats.optimizedExtrusionPoints = optimizedCount
            vstats.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
            self.stats = vstats
        }
        
        let finalMeshes = meshes.compactMap { $0 }
        
        let endTime = CFAbsoluteTimeGetCurrent()
        let elapsedMs = (endTime - startTime) * 1000
        
        DispatchQueue.main.async {
            self.log("⏱ 3D Geometry prep (optimized): \(String(format: "%.2f", elapsedMs)) ms")
            self.processedLayers = finalMeshes
            self.modelBoundingBox = (globalMin, globalMax)
            self.modelSize = globalMax - globalMin
            self.isLoading = false
            self.renderTrigger += 1
        }
    }
    
    private func simplifyPathRDP(points: [simd_float3], epsilon: Float) -> [simd_float3] {
        guard points.count > 2 else { return points }
        
        let count = points.count
        var keep = [Bool](repeating: false, count: count)
        keep[0] = true
        keep[count - 1] = true
        
        var stack = [(start: 0, end: count - 1)]
        while let range = stack.popLast() {
            guard range.end - range.start > 1 else { continue }
            
            var maxDistSq: Float = 0
            var maxIndex = range.start
            
            let startPoint = points[range.start]
            let endPoint = points[range.end]
            let lineVec = endPoint - startPoint
            let lineLenSq = simd_length_squared(lineVec)
            
            for i in range.start + 1 ..< range.end {
                var distSq: Float = 0
                if lineLenSq < 1e-6 {
                    distSq = simd_distance_squared(points[i], startPoint)
                } else {
                    let t = max(0, min(1, simd_dot(points[i] - startPoint, lineVec) / lineLenSq))
                    let projection = startPoint + lineVec * t
                    distSq = simd_distance_squared(points[i], projection)
                }
                if distSq > maxDistSq {
                    maxDistSq = distSq
                    maxIndex = i
                }
            }
            
            if maxDistSq > epsilon * epsilon {
                keep[maxIndex] = true
                stack.append((range.start, maxIndex))
                stack.append((maxIndex, range.end))
            }
        }
        
        var result = [simd_float3]()
        result.reserveCapacity(keep.lazy.filter { $0 }.count)
        for i in 0..<count where keep[i] {
            result.append(points[i])
        }
        return result
    }
    
    private func createTubeBuffersOptimized(for path: [simd_float3],
                                            radius: Float,
                                            segments: Int,
                                            precomputedAngles: [(cos: Float, sin: Float)]) -> (v: [SCNVector3], n: [SCNVector3], i: [Int32])?
    {
        let pointCount = path.count
        guard pointCount >= 2 else { return nil }
        
        let totalVertices = pointCount * segments
        let totalIndices = (pointCount - 1) * segments * 6
        
        var vertices = [SCNVector3]()
        var normals = [SCNVector3]()
        var indices = [Int32]()
        
        vertices.reserveCapacity(totalVertices)
        normals.reserveCapacity(totalVertices)
        indices.reserveCapacity(totalIndices)
        
        var allNormals = [[simd_float3]](repeating: [], count: pointCount)
        
        var T = simd_normalize(path[1] - path[0])
        var N = simd_float3(0, 1, 0)
        if abs(simd_dot(T, N)) > 0.99 { N = simd_float3(1, 0, 0) }
        N = simd_normalize(simd_cross(T, N))
        var B = simd_cross(T, N)
        
        for i in 0..<pointCount {
            if i > 0 {
                let newT = simd_normalize(path[i] - path[i - 1])
                let axis = simd_cross(T, newT)
                let len = simd_length(axis)
                if len > 0.0001 {
                    let angle = acos(min(max(simd_dot(T, newT), -1.0), 1.0))
                    let q = simd_quatf(angle: angle, axis: axis / len)
                    N = q.act(N)
                    B = q.act(B)
                }
                T = newT
            }
            
            var pointNormals = [simd_float3](repeating: simd_float3(repeating: 0), count: segments)
            for j in 0..<segments {
                let (cosA, sinA) = precomputedAngles[j]
                pointNormals[j] = simd_normalize(N * cosA + B * sinA)
            }
            allNormals[i] = pointNormals
        }
        
        for i in 0..<pointCount {
            let pointNormals = allNormals[i]
            for j in 0..<segments {
                let normal = pointNormals[j]
                let pos = path[i] + normal * radius
                normals.append(SCNVector3(normal))
                vertices.append(SCNVector3(pos))
            }
        }
        
        for i in 0..<pointCount - 1 {
            let idx1 = Int32(i * segments)
            let idx2 = Int32((i + 1) * segments)
            for j in 0..<segments {
                let curr1 = idx1 + Int32(j)
                let next1 = idx1 + (Int32(j) + 1) % Int32(segments)
                let curr2 = idx2 + Int32(j)
                let next2 = idx2 + (Int32(j) + 1) % Int32(segments)
                indices.append(curr1)
                indices.append(next1)
                indices.append(curr2)
                indices.append(next1)
                indices.append(next2)
                indices.append(curr2)
            }
        }
        
        return (vertices, normals, indices)
    }
    
    private func createTubeBuffersOptimized0(for path: [simd_float3],
                                            radius: Float,
                                            segments: Int,
                                            precomputedAngles: [(cos: Float, sin: Float)]) -> (v: [SCNVector3], n: [SCNVector3], i: [Int32])?
    {
        let pointCount = path.count
        guard pointCount >= 2 else { return nil }
        
        var vertices = [SCNVector3]()
        var normals = [SCNVector3]()
        var indices = [Int32]()
        
        let totalVertices = pointCount * segments
        vertices.reserveCapacity(totalVertices)
        normals.reserveCapacity(totalVertices)
        indices.reserveCapacity((pointCount - 1) * segments * 6)
        
        var T = simd_normalize(path[1] - path[0])
        var N = simd_float3(0, 1, 0)
        if abs(simd_dot(T, N)) > 0.99 { N = simd_float3(1, 0, 0) }
        N = simd_normalize(simd_cross(T, N))
        var B = simd_cross(T, N)
        
        for i in 0..<pointCount {
            if i > 0 {
                let newT = simd_normalize(path[i] - path[i - 1])
                let axis = simd_cross(T, newT)
                let len = simd_length(axis)
                if len > 0.0001 {
                    let angle = acos(min(max(simd_dot(T, newT), -1.0), 1.0))
                    let q = simd_quatf(angle: angle, axis: axis / len)
                    N = q.act(N)
                    B = q.act(B)
                }
                T = newT
            }
            
            for j in 0..<segments {
                let (cosA, sinA) = precomputedAngles[j]
                let normal = simd_normalize(N * cosA + B * sinA)
                let pos = path[i] + normal * radius
                normals.append(SCNVector3(normal))
                vertices.append(SCNVector3(pos))
            }
        }
        
        for i in 0..<pointCount - 1 {
            let idx1 = Int32(i * segments)
            let idx2 = Int32((i + 1) * segments)
            for j in 0..<segments {
                let curr1 = idx1 + Int32(j)
                let next1 = idx1 + (Int32(j) + 1) % Int32(segments)
                let curr2 = idx2 + Int32(j)
                let next2 = idx2 + (Int32(j) + 1) % Int32(segments)
                indices.append(contentsOf: [curr1, next1, curr2, next1, next2, curr2])
            }
        }
        
        return (vertices, normals, indices)
    }
    
    func applyCollinearAngle() {
        collinearAngle = tempCollinearAngle
        log("Collinear angle changed to \(String(format: "%.1f", collinearAngle))°. Reprocessing ALL models...")
        
        DispatchQueue.global(qos: .userInitiated).async {
            for i in 0..<self.loadedModels.count {
                var model = self.loadedModels[i]
                self.processGeometryForModel(&model)
                DispatchQueue.main.async {
                    self.loadedModels[i] = model
                }
            }
            
            DispatchQueue.main.async {
                self.renderTrigger += 1
                self.log("✅ All models updated with new collinear angle")
            }
        }
    }
    
    func applyDiameter() {
        tubeDiameter = tempTubeDiameter
        log("Diameter changed to \(String(format: "%.1f", tubeDiameter)) mm. Reprocessing ALL models...")
        
        DispatchQueue.global(qos: .userInitiated).async {
            for i in 0..<self.loadedModels.count {
                var model = self.loadedModels[i]
                self.processGeometryForModel(&model)
                DispatchQueue.main.async {
                    self.loadedModels[i] = model
                }
            }
            
            DispatchQueue.main.async {
                self.renderTrigger += 1
                self.log("✅ All models updated with new diameter")
            }
        }
    }
    
    func applyColor() {
        modelColor = tempModelColor
        renderTrigger += 1
        log("Model color updated for all models")
    }

    func changeMaterial(_ material: MaterialPreset) {
        selectedMaterial = material
        renderTrigger += 1
        log("Material changed to \(material.rawValue) for all models")
    }

    // MARK: - Управление освещением

    func applyLightingPreset(_ preset: LightingPreset) {
        let s = preset.settings
        lightingPreset       = preset
        lightingAmbient      = s.ambientIntensity
        lightingMainIntensity = s.mainIntensity
        lightingAngleH       = s.mainAngleH
        lightingAngleV       = s.mainAngleV
        lightingFillIntensity = s.fillIntensity
        lightingTrigger += 1
        log("💡 Lighting preset: \(preset.label)")
    }

    func applyLighting() {
        lightingTrigger += 1
    }
    
    // MARK: - 🆕 Измерение расстояний (Логика)
    
    func addMeasurePoint(_ point: SCNVector3) {
        let simdPoint = simd_float3(Float(point.x), Float(point.y), Float(point.z))
        
        if measurePoints.count >= 2 {
            measurePoints.removeAll()
            measureDistance = ""
        }
        
        measurePoints.append(simdPoint)
        
        if measurePoints.count == 2 {
            calculateMeasureDistance()
        }
        
        renderTrigger += 1
    }
    
    func clearMeasurements() {
        measurePoints.removeAll()
        measureDistance = ""
        renderTrigger += 1
    }
    
    private func calculateMeasureDistance() {
        guard measurePoints.count == 2 else { return }
        
        let p1 = measurePoints[0]
        let p2 = measurePoints[1]
        
        if measureSnapAxis == "None" {
            let distance = simd_distance(p1, p2)
            measureDistance = String(format: "Расстояние: %.2f мм", distance)
        } else {
            let delta: Float
            let axisName: String
            
            switch measureSnapAxis {
            case "X":
                delta = abs(p2.x - p1.x)
                axisName = "X"
            case "Y":
                delta = abs(p2.y - p1.y)
                axisName = "Y"
            case "Z":
                delta = abs(p2.z - p1.z)
                axisName = "Z"
            default:
                delta = 0
                axisName = "?"
            }
            measureDistance = String(format: "Дист. по оси %@: %.2f мм", axisName, delta)
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
    if angleThresholdDeg==0 { return }
    
    let cosThreshold = cos(angleThresholdDeg * Float.pi / 180)
    let cosThresholdSq = cosThreshold * cosThreshold
    
    var filtered = [simd_float3]()
    filtered.reserveCapacity(points.count)
    filtered.append(points[0])
    
    for i in 1..<points.count - 1 {
        let p1 = filtered.last!
        let p2 = points[i]
        let p3 = points[i + 1]
        
        let v1 = p2 - p1
        let v2 = p3 - p2
        
        let len1Sq = simd_length_squared(v1)
        let len2Sq = simd_length_squared(v2)
        
        if len1Sq < 1e-6 || len2Sq < 1e-6 { continue }
        
        let dotProduct = simd_dot(v1, v2)
        
        if dotProduct < 0 {
            filtered.append(p2)
            continue
        }
        
        let dotSq = dotProduct * dotProduct
        if dotSq < cosThresholdSq * len1Sq * len2Sq {
            filtered.append(p2)
        }
    }
    
    filtered.append(points.last!)
    points = filtered
}

extension Color {
    init?(hex: String) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines); hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")
        var rgb: UInt64 = 0; Scanner(string: hexSanitized).scanHexInt64(&rgb)
        self.init(red: Double((rgb & 0xFF0000) >> 16) / 255.0, green: Double((rgb & 0x00FF00) >> 8) / 255.0, blue: Double(rgb & 0x0000FF) / 255.0)
    }
}
