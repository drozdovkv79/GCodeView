import SwiftUI
import SceneKit
import simd

class IosSceneCoordinator {
    var lastRenderTrigger: Int = -1
    var maxDimension: CGFloat = 100.0
    var modelCenterY: CGFloat = 0.0
}

struct IosGCodeSceneView: UIViewRepresentable {
    @EnvironmentObject var appState: AppState
    
    func makeCoordinator() -> IosSceneCoordinator { IosSceneCoordinator() }
    
    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = UIColor.black
        view.scene = SCNScene()
        setupCamera(in: view)
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
    
    func updateUIView(_ uiView: SCNView, context: Context) {
        // 1. Обновление 3D модели (Геометрия или Материал)
        if context.coordinator.lastRenderTrigger != appState.renderTrigger {
            context.coordinator.lastRenderTrigger = appState.renderTrigger
            rebuildScene(uiView: uiView, coordinator: context.coordinator)
        }
        
        // 2. Обработка кнопок камеры
        handleCameraAction(uiView: uiView, coordinator: context.coordinator)
    }
    
    private func handleCameraAction(uiView: SCNView, coordinator: IosSceneCoordinator) {
        guard appState.cameraAction != .none else { return }
        defer { appState.cameraAction = .none }
        
        // Всегда пересоздаем камеру, чтобы сбросить пользовательский поворот пальцами
        setupCamera(in: uiView)
        
        guard let cameraNode = uiView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false),
              let camera = cameraNode.camera else { return }
        
        let fovRad = camera.fieldOfView * .pi / 180.0
        let distance = coordinator.maxDimension * 1.3 / tan(fovRad / 2.0)
        let halfH = coordinator.modelCenterY
        
        let target = SCNVector3(0, halfH, 0)
        var pos = SCNVector3Zero
        var up = SCNVector3(0, 1, 0)
        
        switch appState.cameraAction {
        case .front: pos = SCNVector3(0, halfH, distance)
        case .back: pos = SCNVector3(0, halfH, -distance)
        case .left: pos = SCNVector3(-distance, halfH, 0)
        case .right: pos = SCNVector3(distance, halfH, 0)
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
        SCNTransaction.animationDuration = 0.5 // Плавный поворот камеры на iOS
        cameraNode.position = pos
        cameraNode.look(at: target, up: up, localFront: SCNVector3(0, 0, -1))
        SCNTransaction.commit()
    }
    
    private func rebuildScene(uiView: SCNView, coordinator: IosSceneCoordinator) {
        uiView.scene?.rootNode.childNodes.filter { $0.name == "gcode" }.forEach { $0.removeFromParentNode() }
        
        guard !appState.processedLayers.isEmpty else { return }
        
        let rootNode = SCNNode()
        rootNode.name = "gcode"
        let material = getMaterial(preset: appState.selectedMaterial, color: UIColor(appState.modelColor))
        
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
        
        if let bbox = appState.modelBoundingBox {
            let minX = CGFloat(bbox.min.x); let maxX = CGFloat(bbox.max.x)
            let minY = CGFloat(bbox.min.y); let maxY = CGFloat(bbox.max.y)
            let minZ = CGFloat(bbox.min.z); let maxZ = CGFloat(bbox.max.z)
            
            let centerX = (minX + maxX) / 2.0
            let centerY = (minY + maxY) / 2.0
            let centerZ = (minZ + maxZ) / 2.0
            let halfHeight = (maxY - minY) / 2.0
            
            rootNode.position = SCNVector3(0, halfHeight, 0)
            rootNode.pivot = SCNMatrix4MakeTranslation(Float(centerX), Float(centerY), Float(centerZ))
            
            let sizeX = maxX - minX; let sizeY = maxY - minY; let sizeZ = maxZ - minZ
            let boundingRadius = sqrt(sizeX*sizeX + sizeY*sizeY + sizeZ*sizeZ) / 2.0
            
            coordinator.maxDimension = max(boundingRadius, 1.0)
            coordinator.modelCenterY = halfHeight
        }
        
        uiView.scene?.rootNode.addChildNode(rootNode)
        
        if let cameraNode = uiView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false), cameraNode.camera != nil {
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
    }
    
    // ПОДДЕРЖКА МАТЕРИАЛОВ
    private func getMaterial(preset: MaterialPreset, color: UIColor) -> SCNMaterial {
        let mat = SCNMaterial()
        mat.diffuse.contents = color
        
        switch preset {
        case .plastic:
            mat.lightingModel = .phong
            mat.specular.contents = UIColor(white: 0.5, alpha: 1.0)
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
            mat.diffuse.contents = UIColor(red: 0.8, green: 0.9, blue: 1.0, alpha: 0.5)
        }
        mat.locksAmbientWithDiffuse = true
        return mat
    }
}
