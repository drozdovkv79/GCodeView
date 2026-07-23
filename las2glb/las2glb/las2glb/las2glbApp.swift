import SwiftUI
import Foundation
import simd

// MARK: - Data Models
struct PointCloudData: Sendable {
    var positions: [SIMD3<Float>]
    var colors: [SIMD3<Float>]
}

struct MeshData: Sendable {
    var positions: [SIMD3<Float>]
    var normals: [SIMD3<Float>]
    var colors: [SIMD3<Float>]
    var indices: [UInt32]
}

// MARK: - View Model
@Observable
@MainActor
class ConverterViewModel {
    var inputPath: String = ""
    var outputPath: String = ""
    var targetDecimation: Int = 300_000
    var status: String = "Готов к работе"
    var progress: Double = 0.0
    var isProcessing: Bool = false
    var logs: [String] = []
    
    private var cancelFlag: Bool = false
    
    func log(_ msg: String) {
        logs.append(msg)
        if logs.count > 500 { logs.removeFirst(100) }
    }
    
    func selectInput() async {
        let panel = NSOpenPanel()
        panel.allowedFileTypes = ["las", "laz"]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        
        if panel.runModal() == .OK, let url = panel.url {
            inputPath = url.path
            outputPath = url.deletingPathExtension().path + ".glb"
            log("Выбран файл: \(url.lastPathComponent)")
        }
    }
    
    func startConversion() {
        guard !inputPath.isEmpty, !outputPath.isEmpty else { return }
        isProcessing = true
        cancelFlag = false
        progress = 0
        logs.removeAll()
        
        Task.detached(priority: .userInitiated) { [weak self] in
            guard let self else { return }
            do {
                try await self.runPipeline()
            } catch {
                await self.log("❌ Ошибка: \(error.localizedDescription)")
                await MainActor.run { self.status = "Ошибка" }
            }
            await MainActor.run { self.isProcessing = false }
        }
    }
    
    // MARK: - Main Pipeline
    private func runPipeline() async throws {
        let url = URL(fileURLWithPath: inputPath)
        
        // 1. Read LAS
        await MainActor.run { status = "Чтение LAS..." }
        await log("Чтение: \(inputPath)")
        var data = try Data(contentsOf: url, options: .mappedIfSafe)
        let rawCloud = try LASReader.read(data: &data)
        
        // ⚠️ Защита: проверяем что точки загрузились
        guard rawCloud.positions.count >= 3 else {
            throw NSError(domain: "Pipeline", code: 100,
                         userInfo: [NSLocalizedDescriptionKey: "Загружено слишком мало точек: \(rawCloud.positions.count)"])
        }
        await log("Загружено: \(rawCloud.positions.count) точек")
        await MainActor.run { progress = 0.1 }
        
        // 2. Decimation
        await MainActor.run { status = "Децимация..." }
        let decimated = PointCloudProcessor.voxelDecimate(
            positions: rawCloud.positions,
            colors: rawCloud.colors,
            targetCount: targetDecimation
        )
        
        guard decimated.positions.count >= 3 else {
            throw NSError(domain: "Pipeline", code: 101,
                         userInfo: [NSLocalizedDescriptionKey: "После децимации осталось \(decimated.positions.count) точек. Увеличьте targetDecimation."])
        }
        await log("После децимации: \(decimated.positions.count) точек")
        await MainActor.run { progress = 0.4 }
        
        // 3. Normals
        await MainActor.run { status = "Вычисление нормалей..." }
        let normals = PointCloudProcessor.estimateNormalsGrid(positions: decimated.positions)
        await log("Нормали вычислены")
        await MainActor.run { progress = 0.7 }
        
        // 4. Triangulation (2.5D Delaunay)
        await MainActor.run { status = "Триангуляция (2.5D)..." }
        let mesh = try PointCloudProcessor.triangulate2D(
            positions: decimated.positions,
            normals: normals,
            colors: decimated.colors
        )
        await log("Треугольников: \(mesh.indices.count / 3)")
        await MainActor.run { progress = 0.9 }
        
        // 5. Export GLB
        await MainActor.run { status = "Сохранение GLB..." }
        try GLBExporter.export(mesh: mesh, to: URL(fileURLWithPath: outputPath))
        await log("✅ GLB успешно сохранен!")
        await MainActor.run {
            progress = 1.0
            status = "Готово!"
        }
    }
}

// MARK: - 1. LAS Reader (High-Perf Binary Parser - ИСПРАВЛЕННАЯ ВЕРСИЯ)
enum LASReader {
    static func read(data: inout Data) throws -> PointCloudData {
        guard data.count > 235 else {
            throw NSError(domain: "LAS", code: 1, userInfo: [NSLocalizedDescriptionKey: "Файл слишком мал для LAS"])
        }
        
        // === 1. Проверка сигнатуры "LASF" (сравнение байтов, без ошибок кодирования) ===
        guard data.prefix(4) == Data("LASF".utf8) else {
            throw NSError(domain: "LAS", code: 2, userInfo: [NSLocalizedDescriptionKey: "Неверная сигнатура LAS файла (ожидается 'LASF')"])
        }
        
        // === 2. Чтение заголовка ===
        let versionMinor = data[25]
        
        let offsetToPointData = data.withUnsafeBytes {
            $0.loadUnaligned(fromByteOffset: 96, as: UInt32.self)
        }
        
        let pointFormat = data[104]
        
        let pointRecordLength = data.withUnsafeBytes {
            $0.loadUnaligned(fromByteOffset: 105, as: UInt16.self)
        }
        
        // Количество точек (зависит от версии LAS)
        let numPoints: Int
        if versionMinor >= 4 {
            // LAS 1.4: 64-bit count at offset 247
            numPoints = Int(data.withUnsafeBytes {
                $0.loadUnaligned(fromByteOffset: 247, as: UInt64.self)
            })
        } else {
            // LAS 1.0-1.3: 32-bit count at offset 107
            numPoints = Int(data.withUnsafeBytes {
                $0.loadUnaligned(fromByteOffset: 107, as: UInt32.self)
            })
        }
        
        // Масштаб и смещение
        let xScale = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 131, as: Double.self) }
        let yScale = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 139, as: Double.self) }
        let zScale = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 147, as: Double.self) }
        
        let xOffset = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 155, as: Double.self) }
        let yOffset = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 163, as: Double.self) }
        let zOffset = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 171, as: Double.self) }
        
        // === 3. Определение наличия и смещения цвета (строго по спецификации LAS) ===
        let hasColor: Bool
        let rgbOffset: Int
        
        switch pointFormat {
        case 2:
            hasColor = true
            rgbOffset = 20
        case 3, 5:
            hasColor = true
            rgbOffset = 28 // После GPS Time (8 bytes)
        case 7, 8, 10:
            hasColor = true
            rgbOffset = 30 // В LAS 1.4 смещение сдвинуто из-за изменения структуры
        default:
            hasColor = false
            rgbOffset = 0
        }
        
        // === 4. Выделение памяти ===
        var positions = [SIMD3<Float>]()
        var colors = [SIMD3<Float>]()
        positions.reserveCapacity(numPoints)
        if hasColor { colors.reserveCapacity(numPoints) }
        
        // === 5. Быстрый парсинг точек через указатели ===
        try data.withUnsafeBytes { rawBuffer in
            guard let basePtr = rawBuffer.baseAddress else { return }
            let pointPtr = basePtr.advanced(by: Int(offsetToPointData))
            
            for i in 0..<numPoints {
                let p = pointPtr.advanced(by: i * Int(pointRecordLength))
                
                // Чтение X, Y, Z как Int32
                let x = p.loadUnaligned(as: Int32.self)
                let y = p.loadUnaligned(fromByteOffset: 4, as: Int32.self)
                let z = p.loadUnaligned(fromByteOffset: 8, as: Int32.self)
                
                // Применение масштаба и смещения (как в laspy)
                let px = Float(Double(x) * xScale + xOffset)
                let py = Float(Double(y) * yScale + yOffset)
                let pz = Float(Double(z) * zScale + zOffset)
                positions.append(SIMD3<Float>(px, py, pz))
                
                // Чтение RGB, если присутствует
                if hasColor {
                    let r = p.loadUnaligned(fromByteOffset: rgbOffset, as: UInt16.self)
                    let g = p.loadUnaligned(fromByteOffset: rgbOffset + 2, as: UInt16.self)
                    let b = p.loadUnaligned(fromByteOffset: rgbOffset + 4, as: UInt16.self)
                    
                    // Нормализация (точная копия логики из Python: если max > 255, делим на 65535, иначе на 255)
                    let maxVal: Float = (r > 255 || g > 255 || b > 255) ? 65535.0 : 255.0
                    colors.append(SIMD3<Float>(Float(r)/maxVal, Float(g)/maxVal, Float(b)/maxVal))
                }
            }
        }
        
        // Если цвета нет, задаем нейтральный серый (0.5)
        if !hasColor {
            colors = [SIMD3<Float>](repeating: SIMD3<Float>(0.5, 0.5, 0.5), count: numPoints)
        }
        
        return PointCloudData(positions: positions, colors: colors)
    }
}


// MARK: - 2. Point Cloud Processor
enum PointCloudProcessor {
    
    // O(N) Voxel Decimation using Spatial Hashing (ЗАЩИЩЁННАЯ ВЕРСИЯ)
    static func voxelDecimate(positions: [SIMD3<Float>], colors: [SIMD3<Float>], targetCount: Int) -> PointCloudData {
        // Защита от пустого массива
        guard !positions.isEmpty else {
            return PointCloudData(positions: [], colors: [])
        }
        guard positions.count > targetCount, targetCount > 0 else {
            return PointCloudData(positions: positions, colors: colors)
        }
        
        // Calculate BBox
        var minP = positions[0], maxP = positions[0]
        for p in positions {
            minP = SIMD3<Float>(min(minP.x, p.x), min(minP.y, p.y), min(minP.z, p.z))
            maxP = SIMD3<Float>(max(maxP.x, p.x), max(maxP.y, p.y), max(maxP.z, p.z))
        }
        let bbox = maxP - minP
        let volume = max(bbox.x * bbox.y * bbox.z, 1e-6)
        var voxelSize = pow(volume / Float(targetCount), 1.0/3.0) * 1.2
        voxelSize = max(voxelSize, 1e-6) // защита от нуля
        
        struct VoxelData {
            var sumPos: SIMD3<Float> = .zero
            var sumCol: SIMD3<Float> = .zero
            var count: Int = 0
        }
        
        // ⚠️ ИСПОЛЬЗУЕМ Int64 для защиты от переполнения на больших координатах
        var grid = [SIMD3<Int64>: VoxelData]()
        grid.reserveCapacity(min(targetCount, positions.count))
        
        for i in 0..<positions.count {
            let p = positions[i]
            // Сдвигаем к minP и используем Int64
            let key = SIMD3<Int64>(
                Int64((p.x - minP.x) / voxelSize),
                Int64((p.y - minP.y) / voxelSize),
                Int64((p.z - minP.z) / voxelSize)
            )
            
            if var voxel = grid[key] {
                voxel.sumPos += p
                voxel.sumCol += colors[i]
                voxel.count += 1
                grid[key] = voxel
            } else {
                grid[key] = VoxelData(sumPos: p, sumCol: colors[i], count: 1)
            }
        }
        
        var newPos = [SIMD3<Float>]()
        var newCol = [SIMD3<Float>]()
        newPos.reserveCapacity(grid.count)
        newCol.reserveCapacity(grid.count)
        
        for voxel in grid.values {
            let invCount = 1.0 / Float(voxel.count)
            newPos.append(voxel.sumPos * invCount)
            newCol.append(voxel.sumCol * invCount)
        }
        
        return PointCloudData(positions: newPos, colors: newCol)
    }
    
    // Grid-based Normal Estimation (ЗАЩИЩЁННАЯ ВЕРСИЯ)
    static func estimateNormalsGrid(positions: [SIMD3<Float>], radius: Float? = nil) -> [SIMD3<Float>] {
        let count = positions.count
        
        // Защита от пустого массива
        guard count > 0 else { return [] }
        
        // Защита: если точек меньше 3 — нормали не имеют смысла
        guard count >= 3 else {
            return [SIMD3<Float>](repeating: SIMD3<Float>(0, 0, 1), count: count)
        }
        
        var normals = [SIMD3<Float>](repeating: SIMD3<Float>(0, 0, 1), count: count)
        
        // Вычисляем BBox и searchRadius
        var minP = positions[0], maxP = positions[0]
        for p in positions {
            minP = simd_min(minP, p)
            maxP = simd_max(maxP, p)
        }
        let bbox = maxP - minP
        let volume = max(bbox.x * bbox.y * bbox.z, 1e-6)
        
        let searchRadius: Float
        if let r = radius, r > 0 {
            searchRadius = r
        } else {
            let autoRadius = pow(volume / Float(count), 1.0/3.0) * 3.0
            searchRadius = max(autoRadius, 1e-3) // защита от слишком маленького
        }
        
        // ⚠️ ИСПОЛЬЗУЕМ Int64 + СДВИГ К minP для защиты от переполнения
        var grid = [SIMD3<Int64>: [Int]]()
        grid.reserveCapacity(count)
        
        for i in 0..<count {
            let p = positions[i]
            let key = SIMD3<Int64>(
                Int64((p.x - minP.x) / searchRadius),
                Int64((p.y - minP.y) / searchRadius),
                Int64((p.z - minP.z) / searchRadius)
            )
            grid[key, default: []].append(i)
        }
        
        let searchRadiusSq = searchRadius * searchRadius
        
        for i in 0..<count {
            let p = positions[i]
            let key = SIMD3<Int64>(
                Int64((p.x - minP.x) / searchRadius),
                Int64((p.y - minP.y) / searchRadius),
                Int64((p.z - minP.z) / searchRadius)
            )
            
            var neighbors: [SIMD3<Float>] = []
            neighbors.reserveCapacity(30)
            
            // Check 27 neighboring cells
            for dx: Int64 in -1...1 {
                for dy: Int64 in -1...1 {
                    for dz: Int64 in -1...1 {
                        let nKey = key &+ SIMD3<Int64>(dx, dy, dz)
                        if let cell = grid[nKey] {
                            for idx in cell {
                                let d = positions[idx] - p
                                let distSq = d.x*d.x + d.y*d.y + d.z*d.z
                                if distSq < searchRadiusSq {
                                    neighbors.append(positions[idx])
                                }
                            }
                        }
                    }
                }
            }
            
            if neighbors.count >= 3 {
                // Calculate centroid
                var centroid = SIMD3<Float>.zero
                for n in neighbors { centroid += n }
                centroid /= Float(neighbors.count)
                
                // Find two longest vectors from centroid (fast PCA approximation)
                var maxDist1: Float = 0, maxDist2: Float = 0
                var v1 = SIMD3<Float>.zero, v2 = SIMD3<Float>.zero
                
                for n in neighbors {
                    let d = n - centroid
                    let dist = d.x*d.x + d.y*d.y + d.z*d.z
                    if dist > maxDist1 {
                        maxDist2 = maxDist1; v2 = v1
                        maxDist1 = dist; v1 = d
                    } else if dist > maxDist2 {
                        maxDist2 = dist; v2 = d
                    }
                }
                
                let cross = simd_cross(v1, v2)
                let len = simd_length(cross)
                let normal: SIMD3<Float>
                if len > 1e-6 {
                    normal = cross / len
                } else {
                    normal = SIMD3<Float>(0, 0, 1) // fallback
                }
                
                // Orient normal upwards (Z+)
                normals[i] = normal.z < 0 ? -normal : normal
            }
            // else: остаётся дефолтная (0, 0, 1)
        }
        return normals
    }
    
    // 2.5D Delaunay Triangulation (ЗАЩИЩЁННАЯ ВЕРСИЯ)
    static func triangulate2D(positions: [SIMD3<Float>], normals: [SIMD3<Float>], colors: [SIMD3<Float>]) throws -> MeshData {
        let count = positions.count
        guard count >= 3 else {
            throw NSError(domain: "Mesh", code: 2, userInfo: [NSLocalizedDescriptionKey: "Недостаточно точек для триангуляции (нужно ≥ 3, есть \(count))"])
        }
        guard count == normals.count, count == colors.count else {
            throw NSError(domain: "Mesh", code: 3, userInfo: [NSLocalizedDescriptionKey: "Несоответствие размеров массивов"])
        }
        
        // Project to 2D
        let pts2D = positions.map { SIMD2<Float>($0.x, $0.y) }
        
        var minXY = pts2D[0], maxXY = pts2D[0]
        for p in pts2D {
            minXY = simd_min(minXY, p)
            maxXY = simd_max(maxXY, p)
        }
        
        let dx = maxXY.x - minXY.x
        let dy = maxXY.y - minXY.y
        let dMax = max(dx, dy, 1e-3) * 20
        let midX = (minXY.x + maxXY.x) * 0.5
        let midY = (minXY.y + maxXY.y) * 0.5
        
        var allPts = pts2D
        allPts.append(SIMD2<Float>(midX - dMax, midY - dMax))
        allPts.append(SIMD2<Float>(midX + dMax, midY - dMax))
        allPts.append(SIMD2<Float>(midX, midY + dMax))
        
        let n = count
        var triangles: [(Int, Int, Int)] = [(n, n+1, n+2)]
        
        // Bowyer-Watson
        for i in 0..<n {
            let p = allPts[i]
            var badTriangles: [(Int, Int, Int)] = []
            
            for tri in triangles {
                if inCircle(p, allPts[tri.0], allPts[tri.1], allPts[tri.2]) {
                    badTriangles.append(tri)
                }
            }
            
            var polygon: [(Int, Int)] = []
            for tri in badTriangles {
                let edges = [(tri.0, tri.1), (tri.1, tri.2), (tri.2, tri.0)]
                for edge in edges {
                    var shared = false
                    for other in badTriangles where other != tri {
                        let otherEdges = [(other.0, other.1), (other.1, other.2), (other.2, other.0)]
                        if otherEdges.contains(where: { ($0.0 == edge.1 && $0.1 == edge.0) || ($0.0 == edge.0 && $0.1 == edge.1) }) {
                            shared = true; break
                        }
                    }
                    if !shared { polygon.append(edge) }
                }
            }
            
            triangles.removeAll(where: { tri in
                badTriangles.contains(where: { bt in
                    bt.0 == tri.0 && bt.1 == tri.1 && bt.2 == tri.2
                })
            })
            for edge in polygon {
                triangles.append((edge.0, edge.1, i))
            }
        }
        
        // Remove triangles connected to super-triangle
        let validTris = triangles.filter { $0.0 < n && $0.1 < n && $0.2 < n }
        
        guard !validTris.isEmpty else {
            throw NSError(domain: "Mesh", code: 4, userInfo: [NSLocalizedDescriptionKey: "Триангуляция не создала ни одного валидного треугольника"])
        }
        
        var indices = [UInt32]()
        indices.reserveCapacity(validTris.count * 3)
        for tri in validTris {
            indices.append(UInt32(tri.0))
            indices.append(UInt32(tri.1))
            indices.append(UInt32(tri.2))
        }
        
        return MeshData(positions: positions, normals: normals, colors: colors, indices: indices)
    }
    
    private static func inCircle(_ p: SIMD2<Float>, _ a: SIMD2<Float>, _ b: SIMD2<Float>, _ c: SIMD2<Float>) -> Bool {
        let ax = a.x - p.x, ay = a.y - p.y
        let bx = b.x - p.x, by = b.y - p.y
        let cx = c.x - p.x, cy = c.y - p.y
        let det = ax * (by * (cx*cx + cy*cy) - cy * (bx*bx + by*by)) -
                  ay * (bx * (cx*cx + cy*cy) - cx * (bx*bx + by*by)) +
                  (ax*ax + ay*ay) * (bx * cy - by * cx)
        return det > 0
    }
}

// MARK: - 3. GLB Exporter (ЗАЩИЩЁННАЯ ВЕРСИЯ)
enum GLBExporter {
    static func export(mesh: MeshData, to url: URL) throws {
        let vertexCount = mesh.positions.count
        let indexCount = mesh.indices.count
        
        guard vertexCount >= 3 else {
            throw NSError(domain: "GLB", code: 10, userInfo: [NSLocalizedDescriptionKey: "Недостаточно вершин для GLB (нужно ≥ 3)"])
        }
        guard indexCount >= 3 else {
            throw NSError(domain: "GLB", code: 11, userInfo: [NSLocalizedDescriptionKey: "Недостаточно индексов для GLB"])
        }
        guard vertexCount == mesh.normals.count, vertexCount == mesh.colors.count else {
            throw NSError(domain: "GLB", code: 12, userInfo: [NSLocalizedDescriptionKey: "Несоответствие размеров массивов вершин"])
        }
        
        var binData = Data()
        binData.reserveCapacity(vertexCount * 36 + indexCount * 4)
        
        for i in 0..<vertexCount {
            binData.append(contentsOf: withUnsafeBytes(of: mesh.positions[i]) { Array($0) })
            binData.append(contentsOf: withUnsafeBytes(of: mesh.normals[i]) { Array($0) })
            binData.append(contentsOf: withUnsafeBytes(of: mesh.colors[i]) { Array($0) })
        }
        
        let vertexBufferLength = binData.count
        
        for idx in mesh.indices {
            binData.append(contentsOf: withUnsafeBytes(of: idx) { Array($0) })
        }
        
        while binData.count % 4 != 0 { binData.append(0) }
        let binChunkLength = binData.count
        
        var minB = mesh.positions[0], maxB = mesh.positions[0]
        for p in mesh.positions {
            minB = simd_min(minB, p); maxB = simd_max(maxB, p)
        }
        
        let jsonDict: [String: Any] = [
            "asset": ["version": "2.0", "generator": "Swift LAS2GLB"],
            "scene": 0,
            "scenes": [["nodes": [0]]],
            "nodes": [["mesh": 0]],
            "meshes": [[
                "primitives": [[
                    "attributes": ["POSITION": 0, "NORMAL": 1, "COLOR_0": 2],
                    "indices": 3, "mode": 4
                ]]
            ]],
            "accessors": [
                ["bufferView": 0, "componentType": 5126, "count": vertexCount, "type": "VEC3",
                 "max": [maxB.x, maxB.y, maxB.z], "min": [minB.x, minB.y, minB.z]],
                ["bufferView": 0, "byteOffset": 12, "componentType": 5126, "count": vertexCount, "type": "VEC3"],
                ["bufferView": 0, "byteOffset": 24, "componentType": 5126, "count": vertexCount, "type": "VEC3"],
                ["bufferView": 1, "componentType": 5125, "count": indexCount, "type": "SCALAR"]
            ],
            "bufferViews": [
                ["buffer": 0, "byteOffset": 0, "byteLength": vertexBufferLength, "target": 34962, "byteStride": 36],
                ["buffer": 0, "byteOffset": vertexBufferLength, "byteLength": binChunkLength - vertexBufferLength, "target": 34963]
            ],
            "buffers": [["byteLength": binChunkLength]]
        ]
        
        let jsonData = try JSONSerialization.data(withJSONObject: jsonDict)
        
        var jsonPadded = jsonData
        while jsonPadded.count % 4 != 0 { jsonPadded.append(0x20) }
        
        var glb = Data()
        let totalLength = 12 + 8 + jsonPadded.count + 8 + binChunkLength
        
        glb.append(contentsOf: [0x67, 0x6C, 0x54, 0x46])
        glb.append(contentsOf: withUnsafeBytes(of: UInt32(2)) { Array($0) })
        glb.append(contentsOf: withUnsafeBytes(of: UInt32(totalLength)) { Array($0) })
        
        glb.append(contentsOf: withUnsafeBytes(of: UInt32(jsonPadded.count)) { Array($0) })
        glb.append(contentsOf: [0x4A, 0x53, 0x4F, 0x4E])
        glb.append(jsonPadded)
        
        glb.append(contentsOf: withUnsafeBytes(of: UInt32(binChunkLength)) { Array($0) })
        glb.append(contentsOf: [0x42, 0x49, 0x4E, 0x00])
        glb.append(binData)
        
        try glb.write(to: url)
    }
}


@main
struct LAS2GLBApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
