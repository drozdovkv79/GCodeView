import SwiftUI
import SceneKit
import simd

class GCodeSceneCoordinator {
    weak var sceneView: SCNView?
    var lastRenderTrigger: Int = -1
    var maxDimension: CGFloat = 100.0
    var modelCenterY: CGFloat = 0.0
}

struct GCodeSceneView: NSViewRepresentable {
    @EnvironmentObject var appState: AppState
    
    func makeCoordinator() -> GCodeSceneCoordinator { GCodeSceneCoordinator() }
    
    func makeNSView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = NSColor.black
        //view.antialiasingMode = .multisampling2X
        // 2. Включаем более продвинутый алгоритм временного сглаживания (Jittering),
        view.isJitteringEnabled = true
        
        view.scene = SCNScene()
        setupCamera(in: view)
        context.coordinator.sceneView = view
        appState.sceneView = view

        return view
    }
    
    private func setupCamera(in view: SCNView) {
        view.scene?.rootNode.childNode(withName: "mainCamera", recursively: false)?.removeFromParentNode()
        let cameraNode = SCNNode()
        cameraNode.name = "mainCamera"
        cameraNode.camera = SCNCamera()
        cameraNode.camera?.automaticallyAdjustsZRange = true
        cameraNode.camera?.fieldOfView = 45.0
        view.scene?.rootNode.addChildNode(cameraNode)
        view.pointOfView = cameraNode
    }
    
    func updateNSView(_ nsView: SCNView, context: Context) {
        if context.coordinator.lastRenderTrigger != appState.renderTrigger {
            context.coordinator.lastRenderTrigger = appState.renderTrigger
            rebuildScene(nsView: nsView, coordinator: context.coordinator)
        }
        
        nsView.scene?.rootNode.childNode(withName: "grid", recursively: false)?.isHidden = !appState.showAxis
        handleCameraAction(nsView: nsView, coordinator: context.coordinator)
    }
    
    private func handleCameraAction(nsView: SCNView, coordinator: GCodeSceneCoordinator) {
        guard appState.cameraAction != .none else { return }
        defer { appState.cameraAction = .none }
        
        if appState.cameraAction != .rotate360 {
            setupCamera(in: nsView)
        }
        
        guard let cameraNode = nsView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false),
              let camera = cameraNode.camera else { return }
        
        let fovRad = camera.fieldOfView * .pi / 180.0
        let distance = coordinator.maxDimension * 1.3 / tan(fovRad / 2.0)
        let halfH = coordinator.modelCenterY
        
        let target = SCNVector3(0, halfH, 0)
        var pos = SCNVector3Zero
        var up = SCNVector3(0, 1, 0)
        
        switch appState.cameraAction {
        case .rotate360:
            if let rootNode = nsView.scene?.rootNode.childNode(withName: "gcode", recursively: false) {
                rootNode.removeAllActions()
                let action = SCNAction.rotateBy(x: 0, y: CGFloat(Float.pi * 2), z: 0, duration: 3.0)
                rootNode.runAction(action)
            }
            return
            
        case .front:  pos = SCNVector3(0, halfH, distance)
        case .back:   pos = SCNVector3(0, halfH, -distance)
        case .left:   pos = SCNVector3(-distance, halfH, 0)
        case .right:  pos = SCNVector3(distance, halfH, 0)
        case .top:
            pos = SCNVector3(0, halfH + distance, 0)
            up = SCNVector3(0, 0, -1)
        case .bottom:
            pos = SCNVector3(0, halfH - distance, 0)
            up = SCNVector3(0, 0, -1)
            
        case .iso1: pos = SCNVector3(distance*0.5, halfH + distance*0.5, distance*0.5)
        case .iso2: pos = SCNVector3(-distance*0.5, halfH + distance*0.5, distance*0.5)
        case .iso3: pos = SCNVector3(distance*0.5, halfH + distance*0.5, -distance*0.5)
        case .iso4: pos = SCNVector3(-distance*0.5, halfH + distance*0.5, -distance*0.5)
        default: break
        }
        
        SCNTransaction.begin()
        SCNTransaction.animationDuration = 0
        cameraNode.position = pos
        cameraNode.look(at: target, up: up, localFront: SCNVector3(0, 0, -1))
        SCNTransaction.commit()
    }
    
    private func rebuildScene(nsView: SCNView, coordinator: GCodeSceneCoordinator) {
        let startTime = CFAbsoluteTimeGetCurrent()
        nsView.scene?.rootNode.childNodes.filter { $0.name == "gcode" }.forEach { $0.removeFromParentNode() }
        
        guard !appState.processedLayers.isEmpty else { return }
        
        let rootNode = SCNNode()
        rootNode.name = "gcode"
        let material = getMaterial(preset: appState.selectedMaterial, color: NSColor(appState.modelColor))
        
        for layerData in appState.processedLayers {
            let sourceGeo = SCNGeometrySource(vertices: layerData.vertices)
            let sourceNorm = SCNGeometrySource(normals: layerData.normals)
            let element = SCNGeometryElement(indices: layerData.indices, primitiveType: .triangles)
            let tubeGeometry = SCNGeometry(sources: [sourceGeo, sourceNorm], elements: [element])
            tubeGeometry.materials = [material]
            let layerNode = SCNNode(geometry: tubeGeometry)
            layerNode.name = "layer_\(layerData.id)"
            rootNode.addChildNode(layerNode)
        }
        
        // ИСПРАВЛЕНА ЦЕНТРОВКА: Основание строго на Y=0, центр по X и Z
        if let bbox = appState.modelBoundingBox {
            let minX = CGFloat(bbox.min.x); let maxX = CGFloat(bbox.max.x)
            let minY = CGFloat(bbox.min.y); let maxY = CGFloat(bbox.max.y)
            let minZ = CGFloat(bbox.min.z); let maxZ = CGFloat(bbox.max.z)
            
            // Локальные координаты центра модели
            let centerX = (minX + maxX) / 2.0
            let centerY = (minY + maxY) / 2.0
            let centerZ = (minZ + maxZ) / 2.0
            let halfHeight = (maxY - minY) / 2.0
            
            // 1. Устанавливаем позицию узла так, чтобы ГЕОМЕТРИЧЕСКИЙ ЦЕНТР модели
            // находился в координатах X=0, Z=0 и Y=половина высоты.
            // Это гарантирует, что низ модели будет точно на Y=0 (стол).
            rootNode.position = SCNVector3(0, halfHeight, 0)
            
            // 2. Указываем pivot (ось вращения) как локальный геометрический центр.
            rootNode.pivot = SCNMatrix4MakeTranslation(centerX, centerY, centerZ)
            
            let sizeX = maxX - minX
            let sizeY = maxY - minY
            let sizeZ = maxZ - minZ
            let boundingRadius = sqrt(sizeX*sizeX + sizeY*sizeY + sizeZ*sizeZ) / 2.0
            
            coordinator.maxDimension = max(boundingRadius, 1.0)
            coordinator.modelCenterY = halfHeight // Камера смотрит в центр высоты
        }
        
        nsView.scene?.rootNode.addChildNode(rootNode)
        
        nsView.scene?.rootNode.childNode(withName: "grid", recursively: false)?.removeFromParentNode()
        let gridNode = createGridNode(maxDimension: coordinator.maxDimension)
        gridNode.isHidden = !appState.showAxis
        nsView.scene?.rootNode.addChildNode(gridNode)
        
        if let cameraNode = nsView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false), cameraNode.camera != nil {
            let fovRad = cameraNode.camera!.fieldOfView * .pi / 180.0
            let cameraDistance = coordinator.maxDimension * 1.3 / tan(fovRad / 2.0)
            let halfH = coordinator.modelCenterY
            let target = SCNVector3(0, halfH, 0)
            
            SCNTransaction.begin()
            SCNTransaction.animationDuration = 0
            cameraNode.position = SCNVector3(cameraDistance*0.5, halfH + cameraDistance*0.5, cameraDistance*0.5)
            cameraNode.look(at: target, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 0, -1))
            SCNTransaction.commit()
        }
        
        let endTime = CFAbsoluteTimeGetCurrent()
        appState.log("⏱ 3D Scene Render: \(String(format: "%.2f", (endTime - startTime) * 1000)) ms")
    }
    
    // MARK: - Grid & Axis
    private func createGridNode(maxDimension: CGFloat) -> SCNNode {
        let gridNode = SCNNode(); gridNode.name = "grid"
        let steps: [CGFloat] = [10, 50, 100, 500, 1000, 5000]
        let targetLines: CGFloat = 10.0; let idealStep = maxDimension * 2.0 / targetLines
        var step = steps.last!
        for s in steps { if idealStep <= s { step = s; break } }
        let extent = maxDimension * 2.0; let halfExtent = extent / 2.0
        var vertices: [SCNVector3] = []; var indices: [Int32] = []; var idx: Int32 = 0
        var z = -halfExtent
        while z <= halfExtent + 0.001 { vertices.append(SCNVector3(-halfExtent, 0, z)); vertices.append(SCNVector3(halfExtent, 0, z)); indices.append(idx); indices.append(idx + 1); idx += 2; z += step }
        var x = -halfExtent
        while x <= halfExtent + 0.001 { vertices.append(SCNVector3(x, 0, -halfExtent)); vertices.append(SCNVector3(x, 0, halfExtent)); indices.append(idx); indices.append(idx + 1); idx += 2; x += step }
        let gridGeo = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices)], elements: [SCNGeometryElement(indices: indices, primitiveType: .line)])
        let gridMat = SCNMaterial(); gridMat.diffuse.contents = NSColor.gray; gridMat.lightingModel = .constant; gridMat.isDoubleSided = true; gridGeo.materials = [gridMat]
        gridNode.addChildNode(SCNNode(geometry: gridGeo))
        
        let axisLen = maxDimension * 1.2; let axisRadius = maxDimension * 0.005; let offset = axisLen * 0.05
        let sizeX = CGFloat(max(appState.modelSize.x, 1)); let sizeY = CGFloat(max(appState.modelSize.y, 1)); let sizeZ = CGFloat(max(appState.modelSize.z, 1))
        
        let xGeo = SCNCylinder(radius: axisRadius, height: axisLen); xGeo.materials = [axisMaterial(color: NSColor.red)]; let xAxis = SCNNode(geometry: xGeo); xAxis.eulerAngles = SCNVector3(0, 0, Float.pi/2); xAxis.position = SCNVector3(axisLen/2, 0, 0); gridNode.addChildNode(xAxis)
        gridNode.addChildNode(textNode("X", position: SCNVector3(axisLen + offset, 0, 0), color: NSColor.red)); gridNode.addChildNode(textNode("0", position: SCNVector3(offset, 0, 0), color: NSColor.gray)); gridNode.addChildNode(textNode(String(format: "%.0f", sizeX), position: SCNVector3(axisLen + offset, -offset*2, 0), color: NSColor.gray))
        
        let yGeo = SCNCylinder(radius: axisRadius, height: axisLen); yGeo.materials = [axisMaterial(color: NSColor.green)]; let yAxis = SCNNode(geometry: yGeo); yAxis.position = SCNVector3(0, axisLen/2, 0); gridNode.addChildNode(yAxis)
        gridNode.addChildNode(textNode("Y", position: SCNVector3(0, axisLen + offset, 0), color: NSColor.green)); gridNode.addChildNode(textNode(String(format: "%.0f", sizeY), position: SCNVector3(offset*2, axisLen + offset*2, 0), color: NSColor.gray))
        
        let zGeo = SCNCylinder(radius: axisRadius, height: axisLen); zGeo.materials = [axisMaterial(color: NSColor.blue)]; let zAxis = SCNNode(geometry: zGeo); zAxis.eulerAngles = SCNVector3(Float.pi/2, 0, 0); zAxis.position = SCNVector3(0, 0, axisLen/2); gridNode.addChildNode(zAxis)
        gridNode.addChildNode(textNode("Z", position: SCNVector3(0, 0, axisLen + offset), color: NSColor.blue)); gridNode.addChildNode(textNode(String(format: "%.0f", sizeZ), position: SCNVector3(offset*2, 0, axisLen + offset), color: NSColor.gray))
        
        return gridNode
    }
    
    private func textNode(_ string: String, position: SCNVector3, color: NSColor) -> SCNNode {
        let text = SCNText(string: string, extrusionDepth: 0.1); text.font = NSFont.systemFont(ofSize: 1.0); text.flatness = 0.1
        let mat = SCNMaterial(); mat.diffuse.contents = color; mat.lightingModel = .constant; text.materials = [mat]
        let node = SCNNode(geometry: text); node.position = position
        let scale = CGFloat(max(appState.modelSize.x, 1)) * 0.05; node.scale = SCNVector3(scale, scale, scale)
        return node
    }
    
    private func axisMaterial(color: NSColor) -> SCNMaterial { let mat = SCNMaterial(); mat.diffuse.contents = color; mat.lightingModel = .constant; return mat }
    
    private func getMaterial(preset: MaterialPreset, color: NSColor) -> SCNMaterial {
        let mat = SCNMaterial(); mat.diffuse.contents = color
        switch preset {
        case .matte: mat.lightingModel = .lambert; mat.specular.contents = NSColor.black
        case .plastic: mat.lightingModel = .phong; mat.specular.contents = NSColor(white: 0.5, alpha: 1.0); mat.shininess = 40.0
        case .steel: mat.lightingModel = .physicallyBased; mat.metalness.contents = 1.0; mat.roughness.contents = 0.35
        case .glass: mat.lightingModel = .physicallyBased; mat.metalness.contents = 0.0; mat.roughness.contents = 0.05; mat.transparency = 0.4; mat.diffuse.contents = NSColor(calibratedHue: 0.6, saturation: 0.1, brightness: 0.95, alpha: 0.5)
        }
        mat.locksAmbientWithDiffuse = true; return mat
    }
}
