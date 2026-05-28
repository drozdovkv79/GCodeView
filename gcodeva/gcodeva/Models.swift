import Foundation
import simd
import SwiftUI
import Combine
import SceneKit

/*struct GCodePoint { var x: Float = 0; var y: Float = 0; var z: Float = 0; var e: Float = 0; var feedRate: Float = 0; var layer: Int = 0; var isExtrusion: Bool = false }

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
*/
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
    var estimatedPrintTimeMin: Float = 0
    var numLayers: Int = 0
    var totalExtrusion: Float = 0
    var minEPerPoint: Float = 0
    var maxEPerPoint: Float = 0
    var minEPointCoords: String = ""
    var maxEPointCoords: String = ""
    var tempChanges: [TempChange] = []
    var totalPoints: Int = 0; var travelPoints: Int = 0
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
    @Published var isCalculatingAnalytics: Bool = false // НОВОЕ
    @Published var progress: Double = 0
    @Published var logMessages: [String] = []
    
    @Published var tempTubeDiameter: Float = 4.0
    @Published var tempModelColor: Color = Color(hex: "#e9e5ce")!
    @Published var tubeDiameter: Float = 4.0
    @Published var modelColor: Color = Color(hex: "#e9e5ce")!
    @Published var renderTrigger: Int = 0
    @Published var tempCollinearAngle: Float = 5.0
    @Published var collinearAngle: Float = 5.0
    
    @Published var cameraAction: CameraAction = .none
    @Published var selectedMaterial: MaterialPreset = .matte
    @Published var isRecording: Bool = false
    @Published var videoWidth: Int = 1920
    @Published var videoHeight: Int = 1080
    @Published var showAxis: Bool = true
    @Published var modelSize: simd_float3 = simd_float3(1,1,1)
    @Published var simplifyEpsilon: Float = 0.0  // 0 – авто (радиус трубки)
    
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
        stats = GCodeStats()
        log("📂 Start loading: \(file.lastPathComponent)")
        
        DispatchQueue.global(qos: .userInitiated).async {
            let parseStartTime = CFAbsoluteTimeGetCurrent()
            
            let points = GCodeParser.parse(file: file) { progress in
                DispatchQueue.main.async { self.progress = progress }
            }
            
            let parseEndTime = CFAbsoluteTimeGetCurrent()
            let parseMs = (parseEndTime - parseStartTime) * 1000
            
            DispatchQueue.main.async {
                // Показываем в логе интерфейса
                self.log("⏱ Total Parse Time: \(String(format: "%.0f", parseMs)) ms")
                self.log("📊 Points extracted: \(points.count)")
                
                self.rawPoints = points
                self.tubeDiameter = self.tempTubeDiameter
                self.modelColor = self.tempModelColor
                // Сразу строим 3D сцену
                self.renderTrigger += 1
                self.processGeometry()
                self.calculateAnalytics()
            }
        }
    }
    
    /* НОВОЕ: Вычисление аналитики по кнопке
    func calculateAnalytics() {
        guard !rawPoints.isEmpty else { return }
        isCalculatingAnalytics = true
        log("📊 Calculating analytics...")
        let startTime = CFAbsoluteTimeGetCurrent()
        
        DispatchQueue.global(qos: .userInitiated).async {
            var stats = GCodeStats()
            var extMinX: Float = .greatestFiniteMagnitude, extMaxX: Float = -.greatestFiniteMagnitude
            var extMinY: Float = .greatestFiniteMagnitude, extMaxY: Float = -.greatestFiniteMagnitude
            var extMinZ: Float = .greatestFiniteMagnitude, extMaxZ: Float = -.greatestFiniteMagnitude
            var totalE: Float = 0
            var maxSpeed: Float = 0
            var prevPoint: GCodePoint? = nil
            var extPathLength: Float = 0
            var travPathLength: Float = 0
            var printTime: Float = 0
            var sharpCorners = 0
            var prevExt: GCodePoint? = nil
            var prevPrevExt: GCodePoint? = nil
            
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
                    
                    // Углы
                    if let p2 = prevExt, let p1 = prevPrevExt, p1.layer == point.layer {
                        let v1 = simd_float2(p2.x - p1.x, p2.y - p1.y)
                        let v2 = simd_float2(point.x - p2.x, point.y - p2.y)
                        let l1 = simd_length(v1), l2 = simd_length(v2)
                        if l1 > 0.01 && l2 > 0.01 {
                            let dot = simd_dot(v1/l1, v2/l2)
                            let angle = acos(min(max(dot, -1.0), 1.0)) * (180.0 / Float.pi)
                            if angle < 120.0 { sharpCorners += 1 }
                        }
                    }
                    prevPrevExt = prevExt
                    prevExt = point
                    
                    let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
                    layersOpt[point.layer, default: []].append(pos)
                } else {
                    stats.travelPoints += 1
                }
                
                // Пути и время
                if let prev = prevPoint {
                    let dx = point.x - prev.x
                    let dy = point.y - prev.y
                    let dz = point.z - prev.z
                    let distSq = dx*dx + dy*dy + dz*dz
                    
                    if distSq > 0.0001 {
                        let dist = sqrt(distSq)
                        let speed = point.feedRate > 0 ? point.feedRate : 1000.0
                        if point.isExtrusion { extPathLength += dist } else { travPathLength += dist }
                        printTime += (dist / speed) * 60.0
                    }
                }
                prevPoint = point
            }
            
            // Заполнение Stats
            stats.width = extMaxX - extMinX; stats.length = extMaxY - extMinY; stats.height = extMaxZ - extMinZ
            stats.maxZ = extMaxZ; stats.centerOfMassX = extMinX + stats.width / 2.0; stats.centerOfMassY = extMinY + stats.length / 2.0
            stats.numLayers = (self.rawPoints.map { $0.layer }.max() ?? 0) + 1
            stats.totalMaterial = totalE
            let filamentArea = Float.pi * Float.pi * 0.765625 // (1.75/2)^2
            stats.volume = totalE * filamentArea
            stats.maxSpeed = maxSpeed; stats.extrusionPathLength = extPathLength; stats.travelPathLength = travPathLength
            stats.estimatedPrintTimeMin = printTime / 60.0
            stats.averageFlowRate = extPathLength > 0 ? (stats.volume / extPathLength) : 0
            stats.boundingBoxVolume = stats.width * stats.length * stats.height
            stats.xyFootprintArea = stats.width * stats.length
            stats.modelCompactness = stats.boundingBoxVolume > 0 ? (stats.volume / stats.boundingBoxVolume) : 0
            stats.sharpCornersCount = sharpCorners
            
            // Оптимизация коллинеарности
            var originalCount = 0, optimizedCount = 0
            for (_, var points) in layersOpt {
                originalCount += points.count
                removeCollinearPoints(from: &points, angleThresholdDeg: self.collinearAngle)
                optimizedCount += points.count
            }
            stats.originalExtrusionPoints = originalCount
            stats.optimizedExtrusionPoints = optimizedCount
            stats.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
            
            let endTime = CFAbsoluteTimeGetCurrent()
            
            DispatchQueue.main.async {
                self.stats = stats
                self.isCalculatingAnalytics = false
                self.log("⏱ Analytics calculated in \(String(format: "%.2f", (endTime - startTime) * 1000)) ms")
            }
        }
    }
    */
    
    func calculateAnalytics() {
        guard !rawPoints.isEmpty, let url = selectedFileURL else { return }
        isCalculatingAnalytics = true
        log("📊 Calculating analytics...")
        let startTime = CFAbsoluteTimeGetCurrent()
        
        DispatchQueue.global(qos: .userInitiated).async {
            // 1. Локальный захват массива — убираем ARC overhead от self.rawPoints
            let points = self.rawPoints
            
            var stats = GCodeStats()
            stats.fileName = url.lastPathComponent
            stats.fileSize = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int64) ?? 0
            
            var minX: Float = .greatestFiniteMagnitude, maxX: Float = -.greatestFiniteMagnitude
            var minY: Float = .greatestFiniteMagnitude, maxY: Float = -.greatestFiniteMagnitude
            var minZ: Float = .greatestFiniteMagnitude, maxZ: Float = -.greatestFiniteMagnitude
            var extPath: Float = 0, travPath: Float = 0, printTime: Float = 0
            var maxF: Float = 0
            var extCount = 0
            var maxLayer = 0
            
            var totalE: Float = 0
            var minE: Float = .greatestFiniteMagnitude
            var maxE: Float = 0
            var lastE: Float = 0
            
            var minEPoint = GCodePoint()
            var maxEPoint = GCodePoint()
            
            // Оптимизация словаря слоев: кешируем последний Z, чтобы не хешировать Float каждую итерацию
            var zToLayer: [Float: Int] = [:]
            zToLayer.reserveCapacity(256)
            var lastZ: Float = -.greatestFiniteMagnitude
            var lastLayerForZ: Int = 0
            
            // 2. Используем UnsafeBufferPointer для максимальной скорости обхода массива
            points.withUnsafeBufferPointer { buffer in
                guard let baseAddress = buffer.baseAddress else { return }
                
                for i in 0..<buffer.count {
                    let point = baseAddress[i]
                    
                    // Быстрый маппинг слоев
                    if point.z != lastZ {
                        if let existingLayer = zToLayer[point.z] {
                            lastLayerForZ = existingLayer
                        } else {
                            zToLayer[point.z] = point.layer
                            lastLayerForZ = point.layer
                        }
                        lastZ = point.z
                    }
                    
                    if point.layer > maxLayer { maxLayer = point.layer }
                    
                    if point.isExtrusion {
                        extCount += 1
                        if point.x < minX { minX = point.x }
                        if point.x > maxX { maxX = point.x }
                        if point.y < minY { minY = point.y }
                        if point.y > maxY { maxY = point.y }
                        if point.z < minZ { minZ = point.z }
                        if point.z > maxZ { maxZ = point.z }
                        if point.feedRate > maxF { maxF = point.feedRate }
                        
                        let deltaE = point.e - lastE
                        if deltaE > 0 { // Быстрее чем max(0, ...)
                            totalE += deltaE
                            if deltaE > maxE { maxE = deltaE; maxEPoint = point }
                            if deltaE < minE && deltaE > 0.0001 { minE = deltaE; minEPoint = point }
                        }
                        lastE = point.e
                    }
                    
                    if i > 0 {
                        let prev = baseAddress[i - 1]
                        let dx = point.x - prev.x, dy = point.y - prev.y, dz = point.z - prev.z
                        let distSq = dx*dx + dy*dy + dz*dz
                        
                        if distSq > 0.000001 { // Избегаем sqrt для нулевых перемещений
                            let dist = sqrt(distSq)
                            if point.isExtrusion { extPath += dist } else { travPath += dist }
                            let speed = point.feedRate > 0 ? point.feedRate : 1000.0
                            printTime += dist / speed // feedRate в мм/мин -> время в минутах
                        }
                    }
                }
            }
            
            stats.width = maxX - minX
            stats.length = maxY - minY
            stats.height = maxZ - minZ
            stats.extrusionPoints = extCount
            stats.extrusionPathLength = extPath
            stats.maxSpeedMmPerMin = maxF
            stats.estimatedPrintTimeMin = printTime // Уже в минутах
            stats.numLayers = maxLayer + 1
            stats.totalExtrusion = totalE
            stats.minEPerPoint = minE == .greatestFiniteMagnitude ? 0 : minE
            stats.maxEPerPoint = maxE
            
            let formatCoord = { (p: GCodePoint) -> String in
                "X:\(String(format: "%.2f", p.x)) Y:\(String(format: "%.2f", p.y)) Z:\(String(format: "%.2f", p.z))"
            }
            stats.minEPointCoords = minE == .greatestFiniteMagnitude ? "N/A" : formatCoord(minEPoint)
            stats.maxEPointCoords = maxE == 0 ? "N/A" : formatCoord(maxEPoint)
            
            // 3. Парсинг температур (используем быстрый NSData вместо String(contentsOf:))
            //stats.tempChanges = self.parseTemperatureChangesFast(file: url, zToLayer: zToLayer)
            
            DispatchQueue.main.async {
                if let unwrappedStats = self.stats {
                    stats.originalExtrusionPoints = unwrappedStats.originalExtrusionPoints
                    stats.optimizedExtrusionPoints = unwrappedStats.optimizedExtrusionPoints
                    stats.optimizationReductionPercent = unwrappedStats.optimizationReductionPercent
                }
                self.stats = stats
                self.isCalculatingAnalytics = false
                self.log("⏱ Analytics calculated in \(String(format: "%.2f", (CFAbsoluteTimeGetCurrent() - startTime) * 1000)) ms")
            }
        }
    }
    

    // Сверхбыстрый парсинг чисел прямо из байтов ASCII
    private func extractFloatFromData(data: Data.SubSequence, targetChar: UInt8) -> Float? {
        guard let targetIndex = data.firstIndex(of: targetChar) else { return nil }
        
        var index = data.index(after: targetIndex)
        var isNegative = false
        var hasDot = false
        var result: Float = 0
        var decimalMultiplier: Float = 1
        
        // Проверяем минус
        if index < data.endIndex && data[index] == 45 { // ASCII "-"
            isNegative = true
            index = data.index(after: index)
        }
        
        while index < data.endIndex {
            let byte = data[index]
            if byte >= 48 && byte <= 57 { // Цифры 0-9
                let digit = Float(byte - 48)
                if hasDot {
                    decimalMultiplier *= 0.1
                    result += digit * decimalMultiplier
                } else {
                    result = result * 10 + digit
                }
            } else if byte == 46 && !hasDot { // Точка "."
                hasDot = true
            } else {
                break // Число закончилось
            }
            index = data.index(after: index)
        }
        
        return isNegative ? -result : result
    }
    
    
    
    // MARK: - Optimized processGeometry

    private func processGeometry() {
        let startTime = CFAbsoluteTimeGetCurrent()

        // Параметры
        let radius = Float(tubeDiameter / 2.0)
        _ = simplifyEpsilon > 0 ? simplifyEpsilon : radius * 0.2
        let segments = 8

        // Предвычисление тригонометрии
        let angles: [(cos: Float, sin: Float)] = (0..<segments).map { j in
            let angle = Float(j) / Float(segments) * Float.pi * 2
            return (cos(angle), sin(angle))
        }

        // 1. Однопроходная группировка с конвертацией координат
        var layers: [Int: [simd_float3]] = [:]
        var globalMin = simd_float3(repeating: Float.greatestFiniteMagnitude)
        var globalMax = simd_float3(repeating: -Float.greatestFiniteMagnitude)

        layers.reserveCapacity(3000) // примерная оценка
        for point in rawPoints {
            guard point.isExtrusion else { continue }
            let pos = simd_float3(Float(point.x), Float(point.z), -Float(point.y))
            layers[point.layer, default: []].append(pos)
            globalMin = simd_min(globalMin, pos)
            globalMax = simd_max(globalMax, pos)
        }

        // 2. Параллельное построение мешей по слоям
        let sortedLayers = layers.sorted { $0.key < $1.key }
        let layerCount = sortedLayers.count

        // Массив для результатов, инициализированный nil
        var meshes: [LayerMesh?] = Array(repeating: nil, count: layerCount)

        var originalCount = 0
        var optimizedCount = 0
        DispatchQueue.concurrentPerform(iterations: layerCount) { index in
            var (layerID, points) = sortedLayers[index]

            // Упрощение пути
            //let simplified = simplifyPathRDP(points: points, epsilon: epsilon)
            //guard simplified.count >= 2 else { return }
            originalCount+=points.count
            removeCollinearPoints(from: &points, angleThresholdDeg: collinearAngle)
            optimizedCount+=points.count
            // Генерация буферов
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

        if var vstats = self.stats {  // Используем 'var' вместо 'let'
            vstats.originalExtrusionPoints = originalCount
            vstats.optimizedExtrusionPoints = optimizedCount
            vstats.optimizationReductionPercent = originalCount > 0 ? (1.0 - Double(optimizedCount) / Double(originalCount)) * 100.0 : 0.0
            self.stats = vstats  // Присваиваем обратно
        }
        
        // Убираем nil
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

    // MARK: - Упрощение пути (Ramer–Douglas–Peucker, итеративное)

    private func simplifyPathRDP(points: [simd_float3], epsilon: Float) -> [simd_float3] {
        guard points.count > 2 else { return points }

        let count = points.count
        var keep = [Bool](repeating: false, count: count)
        keep[0] = true
        keep[count - 1] = true

        // Стек диапазонов для обработки
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
                    // Линия практически точка
                    distSq = simd_distance_squared(points[i], startPoint)
                } else {
                    // Расстояние от точки до отрезка
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

        // Собираем результат
        var result = [simd_float3]()
        result.reserveCapacity(keep.lazy.filter { $0 }.count)
        for i in 0..<count where keep[i] {
            result.append(points[i])
        }
        return result
    }

    // MARK: - Оптимизированное создание буферов трубки

    private func createTubeBuffersOptimized(for path: [simd_float3],
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

        // Инициализация системы координат
        var T = simd_normalize(path[1] - path[0])
        var N = simd_float3(0, 1, 0)
        if abs(simd_dot(T, N)) > 0.99 { N = simd_float3(1, 0, 0) }
        N = simd_normalize(simd_cross(T, N))
        var B = simd_cross(T, N)

        for i in 0..<pointCount {
            // Обновление системы координат при изменении направления
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

            // Генерация кольца вершин, используя предвычисленные углы
            for j in 0..<segments {
                let (cosA, sinA) = precomputedAngles[j]
                let normal = simd_normalize(N * cosA + B * sinA)
                let pos = path[i] + normal * radius
                normals.append(SCNVector3(normal))
                vertices.append(SCNVector3(pos))
            }
        }

        // Индексы треугольников
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
        log("Collinear angle changed to \(String(format: "%.1f", collinearAngle))°. Reprocessing geometry...")
        DispatchQueue.global(qos: .userInitiated).async { self.processGeometry() }
    }
    
    func applyDiameter() {
        tubeDiameter = tempTubeDiameter
        log("Diameter changed. Reprocessing geometry...")
        DispatchQueue.global(qos: .userInitiated).async { self.processGeometry() }
    }
    
    func applyColor() { modelColor = tempModelColor; renderTrigger += 1; log("Model color updated") }
    func changeMaterial(_ material: MaterialPreset) { selectedMaterial = material; renderTrigger += 1; log("Material changed to \(material.rawValue)") }
    
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
    
    // Предвычисляем косинус порога (один раз)
    let cosThreshold = cos(angleThresholdDeg * Float.pi / 180)
    let cosThresholdSq = cosThreshold * cosThreshold

    var filtered = [simd_float3]()
    filtered.reserveCapacity(points.count)
    filtered.append(points[0])

    for i in 1..<points.count - 1 {
        let p1 = filtered.last!   // последняя оставленная точка
        let p2 = points[i]
        let p3 = points[i + 1]

        let v1 = p2 - p1
        let v2 = p3 - p2

        let len1Sq = simd_length_squared(v1)
        let len2Sq = simd_length_squared(v2)

        // Исключаем вырожденные участки
        if len1Sq < 1e-6 || len2Sq < 1e-6 { continue }

        let dotProduct = simd_dot(v1, v2)

        // Случай тупого или прямого угла (>90°) – всегда оставляем
        if dotProduct < 0 {
            filtered.append(p2)
            continue
        }

        // Сравниваем квадраты, избегая sqrt
        let dotSq = dotProduct * dotProduct
        if dotSq < cosThresholdSq * len1Sq * len2Sq {
            // Угол больше порога → точка важна, оставляем
            filtered.append(p2)
        }
        // иначе угол слишком мал (почти прямая) – точку пропускаем
    }

    filtered.append(points.last!)
    points = filtered
}

func removeCollinearPoints0(from points: inout [simd_float3], angleThresholdDeg: Float) {
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
