import SwiftUI
import SceneKit
import simd

// MARK: - Расширение SCNVector3 с нужными операторами
extension SCNVector3 {
    static func +(lhs: SCNVector3, rhs: SCNVector3) -> SCNVector3 {
        return SCNVector3(lhs.x + rhs.x, lhs.y + rhs.y, lhs.z + rhs.z)
    }
    static func -(lhs: SCNVector3, rhs: SCNVector3) -> SCNVector3 {
        return SCNVector3(lhs.x - rhs.x, lhs.y - rhs.y, lhs.z - rhs.z)
    }
    static func *(vector: SCNVector3, scalar: Float) -> SCNVector3 {
        let cgScalar = CGFloat(scalar)
        return SCNVector3(vector.x * cgScalar, vector.y * cgScalar, vector.z * cgScalar)
    }
    static func *(scalar: Float, vector: SCNVector3) -> SCNVector3 {
        return vector * scalar
    }
    static func +=(lhs: inout SCNVector3, rhs: SCNVector3) {
        lhs = lhs + rhs
    }
    func normalized() -> SCNVector3 {
        let len = sqrt(x*x + y*y + z*z)
        if len == 0 { return self }
        return SCNVector3(x/len, y/len, z/len)
    }
}

// MARK: - Кастомный SCNView с обработкой мыши
class CustomSCNView: SCNView {
    var cameraDistance: Float = 5.0
    var cameraTheta: Float = 45.0   // градусы, горизонтальный угол
    var cameraPhi: Float = 30.0     // градусы, вертикальный угол
    var cameraTarget: SCNVector3 = SCNVector3(0, 0, 0)
    
    private var lastMouseLocation: CGPoint = .zero
    private var isDraggingLeft = false
    private var isDraggedLeft = false
    private var isDraggingRight = false
    
    weak var cameraNode: SCNNode?
    
    func updateCameraTransform() {
        guard let cameraNode = cameraNode else { return }
        
        let thetaRad = cameraTheta * .pi / 180.0
        let phiRad = cameraPhi * .pi / 180.0
        
        let x = cameraDistance * cos(thetaRad) * cos(phiRad)
        let y = cameraDistance * sin(phiRad)
        let z = cameraDistance * sin(thetaRad) * cos(phiRad)
        
        let position = SCNVector3(x, y, z) + cameraTarget
        cameraNode.position = position
        cameraNode.look(at: cameraTarget)
        
        // 🔧 ВАЖНО: Явно указываем, что верхняя ось - Y (0, 1, 0)
        // Это предотвращает наклон камеры
        cameraNode.look(at: cameraTarget, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 0, -1))
    }
    
    // Вспомогательный метод для получения правильных координат внутри NSView
    private func locationInView(for event: NSEvent) -> CGPoint {
        return convert(event.locationInWindow, from: nil)
    }
    
    // MARK: - Левая кнопка мыши (Вращение)
    override func mouseDown(with event: NSEvent) {
        lastMouseLocation = locationInView(for: event)
        isDraggingLeft = true
    }
    
    override func mouseDragged(with event: NSEvent) {
        let newLocation = locationInView(for: event)
        let deltaX = Float(newLocation.x - lastMouseLocation.x)
        let deltaY = Float(newLocation.y - lastMouseLocation.y)
        
        if isDraggingLeft {
            isDraggedLeft = true
            cameraTheta += deltaX * 0.3
            
            // Было: cameraPhi += deltaY * 0.3
            // Стало (инверсия вверх-вниз):
            cameraPhi -= deltaY * 0.3
            
            cameraPhi = max(-89, min(89, cameraPhi))
            cameraTheta = fmod(cameraTheta, 360.0)
            if cameraTheta < 0 { cameraTheta += 360.0 }
            
            updateCameraTransform()
        }
        
        lastMouseLocation = newLocation
    }
        
    // MARK: - Правая кнопка мыши (Панорамирование)
    override func rightMouseDown(with event: NSEvent) {
        lastMouseLocation = locationInView(for: event)
        isDraggingRight = true
    }
    
    // ВАЖНО: В macOS для правой кнопки вызывается rightMouseDragged, а не mouseDragged!
    override func rightMouseDragged(with event: NSEvent) {
        let newLocation = locationInView(for: event)
        let deltaX = Float(newLocation.x - lastMouseLocation.x)
        let deltaY = Float(newLocation.y - lastMouseLocation.y)
        
        if isDraggingRight {
            guard let cameraNode = cameraNode else { return }
            
            // Берем надежные вектора "вправо" и "вверх" прямо из世界ка cameras
            let right = SCNVector3(cameraNode.simdWorldRight)
            let up = SCNVector3(cameraNode.simdWorldUp)
            
            let panSpeed = cameraDistance * 0.002
            
            // Логика "взять и потянуть": цель должна двигаться ПРОТИВОПОЛОЖНО
            // направлению движения мыши относительно камеры, чтобы объект "тянулся" за курсором
            cameraTarget = cameraTarget - (right * deltaX * panSpeed) - (up * deltaY * panSpeed)
            
            updateCameraTransform()
        }
        
        lastMouseLocation = newLocation
    }
    
    override func rightMouseUp(with event: NSEvent) {
        isDraggingRight = false
    }
    
    // MARK: - Колесико мыши (Зум)
    override func scrollWheel(with event: NSEvent) {
        let delta = Float(event.scrollingDeltaY)
        if delta != 0.0 {
            let zoomFactor = 1.0 - delta * 0.05
            cameraDistance *= zoomFactor
            cameraDistance = max(0.5, min(10000, cameraDistance))
            updateCameraTransform()
        }
    }
    
    // MARK: - 🆕 Измерение расстояний (Обработка кликов)
    override func mouseUp(with event: NSEvent) {
        if isDraggedLeft {
            isDraggedLeft = false
            isDraggingLeft = false
            return
        }
        isDraggingLeft = false
        
        // Доступ к AppState через AppDelegate
        guard let state = AppDelegate.shared.appState,
              state.isMeasuringMode else { return }
        
        let point = convert(event.locationInWindow, from: nil)
        
        // Вызываем hitTest БЕЗ параметра options, чтобы обойти баг моста Swift-ObjC
        let hitResults = self.hitTest(point, options: nil)
        
        if let closestHit = hitResults.first {
            let worldCoordinates = closestHit.worldCoordinates
            DispatchQueue.main.async {
                state.addMeasurePoint(worldCoordinates)
            }
        }
    }

    func setCamera(distance: Float, theta: Float, phi: Float, target: SCNVector3) {
        cameraDistance = distance
        cameraTheta = theta
        cameraPhi = phi
        cameraTarget = target
        updateCameraTransform()
    }
}

// MARK: - GCodeSceneCoordinator
class GCodeSceneCoordinator: NSObject {
    weak var sceneView: CustomSCNView?
    var lastRenderTrigger: Int = -1
    var lastLightingTrigger: Int = -1
    var lastShowTravel: Bool = false // 🆕
    var lastLayerViewLimit: Int = Int.max // 🆕
    var maxDimension: CGFloat = 100.0
    var modelCenterY: CGFloat = 0.0
}

// MARK: - GCodeSceneView
struct GCodeSceneView: NSViewRepresentable {
    @EnvironmentObject var appState: AppState
    
    func makeCoordinator() -> GCodeSceneCoordinator {
        GCodeSceneCoordinator()
    }
    
    func makeNSView(context: Context) -> CustomSCNView {
        let view = CustomSCNView()
        view.autoenablesDefaultLighting = false
        view.backgroundColor = NSColor.black
        view.isJitteringEnabled = true
        
        // ВАЖНО: Отключаем стандартное управление камерой SceneKit,
        // иначе оно будет перехватывать мышь и конфликтовать с нашим кастомным
        view.allowsCameraControl = false
        
        view.scene = SCNScene()
        setupCamera(in: view)
        setupLighting(in: view)
        
        context.coordinator.sceneView = view
        appState.sceneView = view
        
        if let cameraNode = view.scene?.rootNode.childNode(withName: "mainCamera", recursively: false) {
            view.cameraNode = cameraNode
            view.setCamera(distance: 5.0, theta: 45, phi: 30, target: SCNVector3(0, 0, 0))
        }
        
        return view
    }
    

    private func setupCamera(in view: CustomSCNView) {
        view.scene?.rootNode.childNode(withName: "mainCamera", recursively: false)?.removeFromParentNode()
        let cameraNode = SCNNode()
        cameraNode.name = "mainCamera"
        cameraNode.camera = SCNCamera()
        cameraNode.camera?.automaticallyAdjustsZRange = true
        cameraNode.camera?.fieldOfView = 45.0
        view.scene?.rootNode.addChildNode(cameraNode)
        view.pointOfView = cameraNode
    }
    
    // Добавьте этот метод в GCodeSceneView:
    private func setCameraToFront(nsView: CustomSCNView, coordinator: GCodeSceneCoordinator) {
        let fovRad = nsView.pointOfView?.camera?.fieldOfView ?? 45.0
        let fovRadRad = fovRad * .pi / 180.0
        let distance = CGFloat(Float(coordinator.maxDimension)) * 1.3 / tan(fovRadRad / 2.0)
        let halfH = Float(coordinator.modelCenterY)
        let target = SCNVector3(0, halfH, 0)
        
        nsView.setCamera(distance: Float(distance), theta: 0, phi: 0, target: target)
    }

    func updateNSView(_ nsView: CustomSCNView, context: Context) {
        if context.coordinator.lastRenderTrigger != appState.renderTrigger {
            context.coordinator.lastRenderTrigger = appState.renderTrigger
            rebuildScene(nsView: nsView, coordinator: context.coordinator)
            if appState.shouldResetCamera {
                appState.shouldResetCamera = false
                // Устанавливаем камеру во фронтальный вид
                DispatchQueue.main.async {
                    self.setCameraToFront(nsView: nsView, coordinator: context.coordinator)
                }
            }
        }
        
        if context.coordinator.lastLightingTrigger != appState.lightingTrigger {
            context.coordinator.lastLightingTrigger = appState.lightingTrigger
            updateLighting(in: nsView)
        }
        // 🆕 Мгновенное переключение видимости холостых ходов (без перестройки геометрии!)
        if context.coordinator.lastShowTravel != appState.showTravelLines {
            context.coordinator.lastShowTravel = appState.showTravelLines
            let isVisible = appState.showTravelLines
            nsView.scene?.rootNode.enumerateChildNodes { node, _ in
                if node.name == "travel_line_node" {
                    node.isHidden = !isVisible
                }
            }
            return
        }
        // 🆕 Мгновенное переключение видимости слоев (ползунок)
        if context.coordinator.lastLayerViewLimit != appState.layerViewLimit {
            context.coordinator.lastLayerViewLimit = appState.layerViewLimit
            let limit = appState.layerViewLimit
            
            // Ищем контейнер со всеми моделями
            if let container = nsView.scene?.rootNode.childNode(withName: "gcode_container", recursively: false) {
                for modelNode in container.childNodes {
                    // Проверяем каждый слой внутри модели
                    for layerNode in modelNode.childNodes {
                        if let name = layerNode.name, name.hasPrefix("layer_") {
                            if let idStr = name.split(separator: "_").last, let layerId = Int(idStr) {
                                if limit == Int.max {
                                    layerNode.isHidden = false // Показать все
                                } else if limit == -1 {
                                    layerNode.isHidden = true  // Скрыть все
                                } else {
                                    layerNode.isHidden = (layerId > limit) // Скрыть те, что выше лимита
                                }
                            }
                        }
                    }
                }
            }
            return
        }
        
        nsView.scene?.rootNode.childNode(withName: "grid", recursively: false)?.isHidden = !appState.showAxis
        handleCameraAction(nsView: nsView, coordinator: context.coordinator)
    }
    
    // MARK: - Освещение (без изменений)
    private func setupLighting(in view: CustomSCNView) {
        guard let root = view.scene?.rootNode else { return }
        
        let ambient = SCNLight()
        ambient.type = .ambient
        ambient.name = "ambientLight"
        ambient.color = NSColor(white: 1.0, alpha: 1.0)
        ambient.intensity = CGFloat(appState.lightingAmbient * 1000)
        let ambientNode = SCNNode()
        ambientNode.name = "ambientLight"
        ambientNode.light = ambient
        root.addChildNode(ambientNode)
        
        let main = SCNLight()
        main.type = .directional
        main.name = "mainLight"
        main.color = NSColor.white
        main.intensity = CGFloat(appState.lightingMainIntensity * 1000)
        let mainNode = SCNNode()
        mainNode.name = "mainLight"
        mainNode.light = main
        root.addChildNode(mainNode)
        
        let fill = SCNLight()
        fill.type = .directional
        fill.name = "fillLight"
        fill.color = NSColor(red: 0.8, green: 0.85, blue: 1.0, alpha: 1.0)
        fill.intensity = CGFloat(appState.lightingFillIntensity * 1000)
        let fillNode = SCNNode()
        fillNode.name = "fillLight"
        fillNode.light = fill
        root.addChildNode(fillNode)
        
        let rim = SCNLight()
        rim.type = .directional
        rim.name = "rimLight"
        rim.color = NSColor(red: 0.2, green: 0.25, blue: 0.4, alpha: 1.0)
        rim.intensity = 200
        let rimNode = SCNNode()
        rimNode.name = "rimLight"
        rimNode.light = rim
        rimNode.look(at: SCNVector3(0, 0, 0),
                     up: SCNVector3(0, 1, 0),
                     localFront: SCNVector3(0, 0, -1))
        rimNode.position = SCNVector3(0, 500, -1500)
        root.addChildNode(rimNode)
        
        positionMainLight(mainNode)
        positionFillLight(fillNode)
    }
    
    private func updateLighting(in view: CustomSCNView) {
        guard let root = view.scene?.rootNode else { return }
        
        if let node = root.childNode(withName: "ambientLight", recursively: false) {
            node.light?.intensity = CGFloat(appState.lightingAmbient * 1000)
        }
        if let node = root.childNode(withName: "mainLight", recursively: false) {
            node.light?.intensity = CGFloat(appState.lightingMainIntensity * 1000)
            positionMainLight(node)
        }
        if let node = root.childNode(withName: "fillLight", recursively: false) {
            node.light?.intensity = CGFloat(appState.lightingFillIntensity * 1000)
            positionFillLight(node)
        }
    }
    
    private func positionMainLight(_ node: SCNNode) {
        let dist: Float = 2000
        let hRad = (appState.lightingAngleH + 90) * .pi / 180
        let vRad = appState.lightingAngleV * .pi / 180
        let x = cos(hRad) * cos(vRad) * dist
        let y = sin(vRad) * dist
        let z = sin(hRad) * cos(vRad) * dist * 0.3
        node.position = SCNVector3(x, y, z)
        node.look(at: SCNVector3(0, 0, 0),
                  up: SCNVector3(0, 1, 0),
                  localFront: SCNVector3(0, 0, -1))
    }
    
    private func positionFillLight(_ node: SCNNode) {
        let dist: Float = 2000
        let hRad = (appState.lightingAngleH + 90 + 180) * .pi / 180
        let vRad = Float(-15) * .pi / 180
        let x = cos(hRad) * cos(vRad) * dist
        let y = sin(vRad) * dist
        let z = sin(hRad) * cos(vRad) * dist * 0.3
        node.position = SCNVector3(x, y, z)
        node.look(at: SCNVector3(0, 0, 0),
                  up: SCNVector3(0, 1, 0),
                  localFront: SCNVector3(0, 0, -1))
    }
    
    // MARK: - Действия камеры (для кнопок)
    private func handleCameraAction(nsView: CustomSCNView, coordinator: GCodeSceneCoordinator) {
        guard appState.cameraAction != .none else { return }
        defer { appState.cameraAction = .none }
        
        if appState.cameraAction == .rotate360 {
            if let rootNode = nsView.scene?.rootNode.childNode(withName: "gcode_container", recursively: false) {
                rootNode.removeAllActions()
                let action = SCNAction.rotateBy(x: 0, y: CGFloat(Float.pi * 2), z: 0, duration: 3.0)
                rootNode.runAction(action)
            }
            return
        }
        
        let fovRad = nsView.pointOfView?.camera?.fieldOfView ?? 45.0
        let fovRadRad = fovRad * .pi / 180.0
        let distance = CGFloat(Float(coordinator.maxDimension)) * 1.3 / tan(fovRadRad / 2.0)
        let halfH = Float(coordinator.modelCenterY)
        let target = SCNVector3(0, halfH, 0)
        
        var theta: Float = 0
        var phi: Float = 0
        var newDistance = distance
        
        switch appState.cameraAction {
        case .front:  theta = 0;   phi = 0; newDistance = distance * 0.8
        case .back:   theta = 180; phi = 0
        case .left:   theta = -90; phi = 0
        case .right:  theta = 90;  phi = 0
        case .top:    theta = 0;   phi = 90; newDistance = distance * 0.8
        case .bottom: theta = 0;   phi = -90; newDistance = distance * 0.8
        case .iso1:   theta = 45;  phi = 30; newDistance = distance * 0.9
        case .iso2:   theta = -45; phi = 30
        case .iso3:   theta = 45;  phi = -30
        case .iso4:   theta = -45; phi = -30
        default: break
        }
        
        nsView.setCamera(distance: Float(newDistance), theta: theta, phi: phi, target: target)
    }
    
    // MARK: - Построение сцены
    private func rebuildScene(nsView: CustomSCNView, coordinator: GCodeSceneCoordinator) {
        let startTime = CFAbsoluteTimeGetCurrent()
        nsView.scene?.rootNode.childNodes.filter { $0.name == "gcode_container" }.forEach { $0.removeFromParentNode() }
        
        guard !appState.loadedModels.isEmpty else { return }
        
        let containerNode = SCNNode()
        containerNode.name = "gcode_container"
        let material = getMaterial(preset: appState.selectedMaterial, color: NSColor(appState.modelColor))
        
        var allModelsMinX: Float = .greatestFiniteMagnitude
        var allModelsMaxX: Float = -.greatestFiniteMagnitude
        var allModelsMinY: Float = .greatestFiniteMagnitude
        var allModelsMaxY: Float = -.greatestFiniteMagnitude
        var allModelsMinZ: Float = .greatestFiniteMagnitude
        var allModelsMaxZ: Float = -.greatestFiniteMagnitude
        
        for model in appState.loadedModels where model.isVisible {
            guard !model.processedLayers.isEmpty else { continue }
            
            let modelNode = SCNNode()
            modelNode.name = "model_\(model.id.uuidString)"
            
            for layerData in model.processedLayers {
                let sourceGeo = SCNGeometrySource(vertices: layerData.vertices)
                let sourceNorm = SCNGeometrySource(normals: layerData.normals)
                let element = SCNGeometryElement(indices: layerData.indices, primitiveType: .triangles)
                let tubeGeometry = SCNGeometry(sources: [sourceGeo, sourceNorm], elements: [element])
                tubeGeometry.materials = [material]
                let layerNode = SCNNode(geometry: tubeGeometry)
                layerNode.name = "layer_\(layerData.id)"
                modelNode.addChildNode(layerNode)
            }
            
            modelNode.position = SCNVector3(model.position.x, model.position.y, model.position.z)
            // 🆕 Применяем сохраненный поворот вокруг оси Y
            modelNode.eulerAngles.y = CGFloat(model.rotationY)
            
            if let bbox = model.boundingBox {
                let minX = bbox.min.x + model.position.x
                let maxX = bbox.max.x + model.position.x
                let minY = bbox.min.y + model.position.y
                let maxY = bbox.max.y + model.position.y
                let minZ = bbox.min.z + model.position.z
                let maxZ = bbox.max.z + model.position.z
                
                allModelsMinX = min(allModelsMinX, minX)
                allModelsMaxX = max(allModelsMaxX, maxX)
                allModelsMinY = min(allModelsMinY, minY)
                allModelsMaxY = max(allModelsMaxY, maxY)
                allModelsMinZ = min(allModelsMinZ, minZ)
                allModelsMaxZ = max(allModelsMaxZ, maxZ)
            }
            
            containerNode.addChildNode(modelNode)
            // 🆕 Отрисовка предрасчитанных труб без экструзии
            let travelMat = getTravelMaterial()
            for travelMesh in model.travelMeshes {
                let tSourceGeo = SCNGeometrySource(vertices: travelMesh.vertices)
                let tSourceNorm = SCNGeometrySource(normals: travelMesh.normals)
                let tElement = SCNGeometryElement(indices: travelMesh.indices, primitiveType: .triangles)
                let travelGeo = SCNGeometry(sources: [tSourceGeo, tSourceNorm], elements: [tElement])
                travelGeo.materials = [travelMat]
                
                let tNode = SCNNode(geometry: travelGeo)
                tNode.name = "travel_line_node"
                // Применяем те же позицию и поворот, что и у основной модели
                tNode.position = SCNVector3(model.position.x, model.position.y, model.position.z)
                tNode.eulerAngles.y = CGFloat(model.rotationY)
                tNode.isHidden = !appState.showTravelLines // Учитываем текущее состояние кнопки
                
                modelNode.addChildNode(tNode) // Добавляем внутрь modelNode, чтобы удалялось вместе с моделью
            }
            
        }
        
        nsView.scene?.rootNode.addChildNode(containerNode)
        
        if allModelsMinX != .greatestFiniteMagnitude {
            let sizeX = allModelsMaxX - allModelsMinX
            let sizeY = allModelsMaxY - allModelsMinY
            let sizeZ = allModelsMaxZ - allModelsMinZ
            let boundingRadius = sqrt(sizeX*sizeX + sizeY*sizeY + sizeZ*sizeZ) / 2.0
            
            coordinator.maxDimension = CGFloat(max(boundingRadius, 1.0))
            coordinator.modelCenterY = CGFloat((allModelsMinY + allModelsMaxY) / 2.0)
        }
        
        nsView.scene?.rootNode.childNode(withName: "grid", recursively: false)?.removeFromParentNode()
        let gridNode = createGridNode(maxDimension: coordinator.maxDimension)
        gridNode.isHidden = !appState.showAxis
        nsView.scene?.rootNode.addChildNode(gridNode)
        
        if let cameraNode = nsView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false) {
            nsView.cameraNode = cameraNode
            let target = SCNVector3(0, Float(coordinator.modelCenterY), 0)
            nsView.setCamera(distance: nsView.cameraDistance, theta: nsView.cameraTheta, phi: nsView.cameraPhi, target: target)
        }
        
        // MARK: - 🆕 Отрисовка измерений
        nsView.scene?.rootNode.childNode(withName: "measure_helper", recursively: false)?.removeFromParentNode()
        
        if !appState.measurePoints.isEmpty {
            let measureNode = SCNNode()
            measureNode.name = "measure_helper"
            
            // Шарик для первой точки (Желтый)
            let sphere1 = SCNSphere(radius: coordinator.maxDimension * 0.008)
            sphere1.firstMaterial?.diffuse.contents = NSColor.systemYellow
            sphere1.firstMaterial?.emission.contents = NSColor.systemYellow
            sphere1.firstMaterial?.lightingModel = .constant
            let node1 = SCNNode(geometry: sphere1)
            node1.position = SCNVector3(appState.measurePoints[0])
            measureNode.addChildNode(node1)
            
            if appState.measurePoints.count == 2 {
                // Шарик для второй точки (Красный)
                let sphere2 = SCNSphere(radius: coordinator.maxDimension * 0.008)
                sphere2.firstMaterial?.diffuse.contents = NSColor.systemRed
                sphere2.firstMaterial?.emission.contents = NSColor.systemRed
                sphere2.firstMaterial?.lightingModel = .constant
                let node2 = SCNNode(geometry: sphere2)
                node2.position = SCNVector3(appState.measurePoints[1])
                measureNode.addChildNode(node2)
                
                // Линия между ними
                let lineGeometry = createLineGeometry(
                    from: SCNVector3(appState.measurePoints[0]),
                    to: SCNVector3(appState.measurePoints[1]),
                    color: NSColor.systemYellow,
                    radius: CGFloat(coordinator.maxDimension * 0.003)
                )
                measureNode.addChildNode(lineGeometry)
            }
            
            nsView.scene?.rootNode.addChildNode(measureNode)
        }

        let endTime = CFAbsoluteTimeGetCurrent()
        appState.log("⏱ 3D Scene Render (\(appState.loadedModels.count) models): \(String(format: "%.2f", (endTime - startTime) * 1000)) ms")
    }
    
    // MARK: - Grid & Axis
    private func createGridNode(maxDimension: CGFloat) -> SCNNode {
        let gridNode = SCNNode()
        gridNode.name = "grid"
        let steps: [CGFloat] = [10, 50, 100, 500, 1000, 5000]
        let targetLines: CGFloat = 10.0
        let idealStep = maxDimension * 2.0 / targetLines
        var step = steps.last!
        for s in steps {
            if idealStep <= s {
                step = s
                break
            }
        }
        let extent = maxDimension * 2.0
        let halfExtent = extent / 2.0
        var vertices: [SCNVector3] = []
        var indices: [Int32] = []
        var idx: Int32 = 0
        
        var z = -halfExtent
        while z <= halfExtent + 0.001 {
            vertices.append(SCNVector3(-halfExtent, 0, z))
            vertices.append(SCNVector3(halfExtent, 0, z))
            indices.append(idx)
            indices.append(idx + 1)
            idx += 2
            z += step
        }
        
        var x = -halfExtent
        while x <= halfExtent + 0.001 {
            vertices.append(SCNVector3(x, 0, -halfExtent))
            vertices.append(SCNVector3(x, 0, halfExtent))
            indices.append(idx)
            indices.append(idx + 1)
            idx += 2
            x += step
        }
        
        let gridGeo = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices)],
                                  elements: [SCNGeometryElement(indices: indices, primitiveType: .line)])
        let gridMat = SCNMaterial()
        gridMat.diffuse.contents = NSColor.gray
        gridMat.lightingModel = .constant
        gridMat.isDoubleSided = true
        gridGeo.materials = [gridMat]
        gridNode.addChildNode(SCNNode(geometry: gridGeo))
        
        let axisLen = maxDimension * 1.2
        let axisRadius = maxDimension * 0.005
        let offset = axisLen * 0.05
        
        let xGeo = SCNCylinder(radius: axisRadius, height: axisLen)
        xGeo.materials = [axisMaterial(color: NSColor.red)]
        let xAxis = SCNNode(geometry: xGeo)
        xAxis.eulerAngles = SCNVector3(0, 0, Float.pi/2)
        xAxis.position = SCNVector3(axisLen/2, 0, 0)
        gridNode.addChildNode(xAxis)
        gridNode.addChildNode(textNode("X", position: SCNVector3(axisLen + offset, 0, 0), color: NSColor.red))
        gridNode.addChildNode(textNode("0", position: SCNVector3(offset, 0, 0), color: NSColor.gray))
        
        let yGeo = SCNCylinder(radius: axisRadius, height: axisLen)
        yGeo.materials = [axisMaterial(color: NSColor.green)]
        let yAxis = SCNNode(geometry: yGeo)
        yAxis.position = SCNVector3(0, axisLen/2, 0)
        gridNode.addChildNode(yAxis)
        gridNode.addChildNode(textNode("Y", position: SCNVector3(0, axisLen + offset, 0), color: NSColor.green))
        
        let zGeo = SCNCylinder(radius: axisRadius, height: axisLen)
        zGeo.materials = [axisMaterial(color: NSColor.blue)]
        let zAxis = SCNNode(geometry: zGeo)
        zAxis.eulerAngles = SCNVector3(Float.pi/2, 0, 0)
        zAxis.position = SCNVector3(0, 0, axisLen/2)
        gridNode.addChildNode(zAxis)
        gridNode.addChildNode(textNode("Z", position: SCNVector3(0, 0, axisLen + offset), color: NSColor.blue))
        
        return gridNode
    }
    
    private func textNode(_ string: String, position: SCNVector3, color: NSColor) -> SCNNode {
        let text = SCNText(string: string, extrusionDepth: 0.1)
        text.font = NSFont.systemFont(ofSize: 1.0)
        text.flatness = 0.1
        let mat = SCNMaterial()
        mat.diffuse.contents = color
        mat.lightingModel = .constant
        text.materials = [mat]
        let node = SCNNode(geometry: text)
        node.position = position
        let scale = CGFloat(max(appState.modelSize.x, 1)) * 0.05
        node.scale = SCNVector3(scale, scale, scale)
        return node
    }
    
    private func axisMaterial(color: NSColor) -> SCNMaterial {
        let mat = SCNMaterial()
        mat.diffuse.contents = color
        mat.lightingModel = .constant
        return mat
    }
    
    // MARK: - 🆕 Создание 3D линии (цилиндр) между двумя точками
    private func createLineGeometry(from: SCNVector3, to: SCNVector3, color: NSColor, radius: CGFloat) -> SCNNode {
        let vector = SCNVector3(to.x - from.x, to.y - from.y, to.z - from.z)
        let distance = sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
        
        guard distance > 0 else { return SCNNode() }
        
        let cylinder = SCNCylinder(radius: radius, height: CGFloat(distance))
        cylinder.firstMaterial?.diffuse.contents = color
        cylinder.firstMaterial?.emission.contents = color
        cylinder.firstMaterial?.lightingModel = .constant
        
        let lineNode = SCNNode(geometry: cylinder)
        lineNode.position = SCNVector3((from.x + to.x) / 2, (from.y + to.y) / 2, (from.z + to.z) / 2)
        
        let yAxis = SCNVector3(0, 1, 0)
        /*let normalizedVector = SCNVector3(vector.x / Float(distance), vector.y / Float(distance), vector.z / Float(distance))
        
        let cross = SCNVector3(yAxis.y * normalizedVector.z - yAxis.z * normalizedVector.y,
                               yAxis.z * normalizedVector.x - yAxis.x * normalizedVector.z,
                               yAxis.x * normalizedVector.y - yAxis.y * normalizedVector.x)
        */
        // 1. Сразу конвертируем дистанцию в Float
        let floatDistance = CGFloat(distance)

        // 2. Выносим координаты в простые переменные
        let vx = vector.x
        let vy = vector.y
        let vz = vector.z

        // 3. Вычисляем и собираем вектор
        let normalizedVector = SCNVector3(vx / floatDistance, vy / floatDistance, vz / floatDistance)
        
        // 1. Извлекаем компоненты векторов в простые переменные (CGFloat или Float)
        let yx = yAxis.x
        let yy = yAxis.y
        let yz = yAxis.z

        let nx = normalizedVector.x
        let ny = normalizedVector.y
        let nz = normalizedVector.z

        // 2. Считаем каждую компоненту отдельно
        let crossX = yy * nz - yz * ny
        let crossY = yz * nx - yx * nz
        let crossZ = yx * ny - yy * nx

        // 3. Инициализируем итоговый вектор
        let cross = SCNVector3(crossX, crossY, crossZ)
        
        
        let dot = yAxis.x * normalizedVector.x + yAxis.y * normalizedVector.y + yAxis.z * normalizedVector.z
        
        let angle = acos(min(max(dot, -1.0), 1.0))
        
        lineNode.rotation = SCNVector4(cross.x, cross.y, cross.z, CGFloat(angle))
        
        return lineNode
    }

    // 🆕 Материал для линий без экструзии
    private func getTravelMaterial() -> SCNMaterial {
        let mat = SCNMaterial()
        mat.diffuse.contents = NSColor.systemBlue
        mat.emission.contents = NSColor.systemBlue.withAlphaComponent(0.8) // Немного подсвечиваем
        mat.lightingModel = .constant // Не зависим от теней и света
        return mat
    }
    
    private func getMaterial(preset: MaterialPreset, color: NSColor) -> SCNMaterial {
        let mat = SCNMaterial()
        mat.diffuse.contents = color
        switch preset {
        case .matte:
            mat.lightingModel = .lambert
            mat.specular.contents = NSColor.black
        case .plastic:
            mat.lightingModel = .phong
            mat.specular.contents = NSColor(white: 0.5, alpha: 1.0)
            mat.shininess = 40.0
        case .steel:
            mat.lightingModel = .physicallyBased
            mat.metalness.contents = 1.0
            mat.roughness.contents = 0.35
        case .glass:
            mat.lightingModel = .physicallyBased
            mat.metalness.contents = 0.0
            mat.roughness.contents = 0.05
            mat.transparency = 0.4
            mat.diffuse.contents = NSColor(calibratedHue: 0.6, saturation: 0.1, brightness: 0.95, alpha: 0.5)
        }
        mat.locksAmbientWithDiffuse = true
        return mat
    }
}
