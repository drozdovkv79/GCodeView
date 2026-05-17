import SwiftUI
import SceneKit
import simd

class SceneViewState {
    var lastRenderTrigger: Int = -1
    var maxDimension: CGFloat = 100.0
}

struct GCodeSceneView: NSViewRepresentable {
    @EnvironmentObject var appState: AppState
    
    func makeCoordinator() -> SceneViewState { SceneViewState() }
    
    func makeNSView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = NSColor.black
        view.scene = SCNScene()
        setupCamera(in: view)
        return view
    }
    
    private func setupCamera(in view: SCNView) {
        // Удаляем старую камеру если есть
        view.scene?.rootNode.childNode(withName: "mainCamera", recursively: false)?.removeFromParentNode()
        
        let cameraNode = SCNNode()
        cameraNode.name = "mainCamera"
        cameraNode.camera = SCNCamera()
        cameraNode.camera?.automaticallyAdjustsZRange = true
        cameraNode.camera?.fieldOfView = 45.0
        cameraNode.position = SCNVector3(x: 0, y: 0, z: 100)
        view.scene?.rootNode.addChildNode(cameraNode)
        view.pointOfView = cameraNode
    }
    
    func updateNSView(_ nsView: SCNView, context: Context) {
        if context.coordinator.lastRenderTrigger != appState.renderTrigger {
            context.coordinator.lastRenderTrigger = appState.renderTrigger
            rebuildScene(nsView: nsView, state: context.coordinator)
        }
        
        handleCameraAction(nsView: nsView, state: context.coordinator)
    }
    
    private func handleCameraAction(nsView: SCNView, state: SceneViewState) {
        guard appState.cameraAction != .none else { return }
        defer { appState.cameraAction = .none }
        
        if appState.cameraAction == .rotate360 {
            if let rootNode = nsView.scene?.rootNode.childNode(withName: "gcode", recursively: false) {
                rootNode.removeAllActions()
                let action = SCNAction.rotateBy(x: 0, y: CGFloat(Float.pi * 2), z: 0, duration: 3.0)
                rootNode.runAction(action)
            }
            return
        }
        
        // Сбрасываем камеру пересозданием, чтобы убрать конфликт ручного вращения
        setupCamera(in: nsView)
        
        guard let cameraNode = nsView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false),
              let camera = cameraNode.camera else { return }
        
        let fovRad = camera.fieldOfView * .pi / 180.0
        let distance = CGFloat(state.maxDimension) * 1.2 / (2 * tan(fovRad / 2))
        
        var pos = SCNVector3Zero
        var up = SCNVector3(0, 1, 0)
        let localFront = SCNVector3(0, 0, -1)
        
        switch appState.cameraAction {
        case .front:  pos = SCNVector3(0, 0, distance)
        case .back:   pos = SCNVector3(0, 0, -distance)
        case .left:   pos = SCNVector3(-distance, 0, 0)
        case .right:  pos = SCNVector3(distance, 0, 0)
        case .top:    pos = SCNVector3(0, distance, 0); up = SCNVector3(0, 0, -1)
        case .bottom: pos = SCNVector3(0, -distance, 0); up = SCNVector3(0, 0, 1)
        case .iso1: pos = SCNVector3(distance, distance, distance)
        case .iso2: pos = SCNVector3(-distance, distance, distance)
        case .iso3: pos = SCNVector3(distance, distance, -distance)
        case .iso4: pos = SCNVector3(-distance, distance, -distance)
        default: break
        }
        
        SCNTransaction.begin()
        SCNTransaction.animationDuration = 0.8
        cameraNode.position = pos
        cameraNode.look(at: SCNVector3(0,0,0), up: up, localFront: localFront)
        SCNTransaction.commit()
    }
    
    private func rebuildScene(nsView: SCNView, state: SceneViewState) {
        guard !appState.rawPoints.isEmpty else { return }
        
        nsView.scene?.rootNode.childNodes.filter { $0.name == "gcode" }.forEach { $0.removeFromParentNode() }
        
        let rootNode = SCNNode()
        rootNode.name = "gcode"
        
        let extPts = appState.rawPoints.filter { $0.isExtrusion }
        let radius = Float(appState.tubeDiameter / 2.0)
        let material = getMaterial(preset: appState.selectedMaterial, color: NSColor(appState.modelColor))
        
        var layers: [Int: [simd_float3]] = [:]
        for point in extPts {
            let pos = simd_float3(Float(point.x), Float(point.z), Float(point.y))
            layers[point.layer, default: []].append(pos)
        }
        
        for (layerIndex, var points) in layers.sorted(by: { $0.key < $1.key }) {
            if points.count < 2 { continue }
            removeCollinearPoints(from: &points, angleThresholdDeg: 5.0)
            if points.count < 2 { continue }
            
            if let tubeGeometry = createTubeGeometry(for: points, radius: radius, segments: 8) {
                tubeGeometry.materials = [material]
                let layerNode = SCNNode(geometry: tubeGeometry)
                layerNode.name = "layer_\(layerIndex)"
                rootNode.addChildNode(layerNode)
            }
        }
        
        let boundingBox = rootNode.boundingBox
        let dx = (boundingBox.min.x + boundingBox.max.x) / 2.0
        let dy = (boundingBox.min.y + boundingBox.max.y) / 2.0
        let dz = boundingBox.min.z // Z не центрируем, основание в 0
        rootNode.position = SCNVector3(-dx, -dy, -dz)
        
        nsView.scene?.rootNode.addChildNode(rootNode)
        
        let sizeX = boundingBox.max.x - boundingBox.min.x
        let sizeY = boundingBox.max.y - boundingBox.min.y
        let sizeZ = boundingBox.max.z - boundingBox.min.z
        state.maxDimension = max(sizeX, sizeY, sizeZ)
        
        if let cameraNode = nsView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false) {
            let cameraDistance = state.maxDimension * 1.5
            cameraNode.position = SCNVector3(x: cameraDistance * 0.5, y: cameraDistance * 0.5, z: cameraDistance)
            cameraNode.look(at: SCNVector3(0,0,0), up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 0, -1))
        }
    }
    
    private func getMaterial(preset: MaterialPreset, color: NSColor) -> SCNMaterial {
        let mat = SCNMaterial()
        mat.diffuse.contents = color
        
        switch preset {
        case .plastic:
            mat.lightingModel = .phong; mat.specular.contents = NSColor(white: 0.5, alpha: 1.0); mat.shininess = 40.0
        case .gypsum:
            mat.lightingModel = .lambert; mat.specular.contents = NSColor.black
        case .wood:
            mat.lightingModel = .lambert; mat.diffuse.contents = NSColor(red: 0.6, green: 0.4, blue: 0.2, alpha: 1.0)
        case .steel:
            mat.lightingModel = .physicallyBased; mat.metalness.contents = 1.0; mat.roughness.contents = 0.35
        case .fiberglass:
            mat.lightingModel = .phong; mat.diffuse.contents = NSColor(calibratedHue: 0.55, saturation: 0.3, brightness: 0.8, alpha: 0.9); mat.specular.contents = NSColor.white; mat.shininess = 80.0; mat.transparency = 0.85
        case .glass:
            mat.lightingModel = .physicallyBased; mat.metalness.contents = 0.0; mat.roughness.contents = 0.05; mat.transparency = 0.4; mat.diffuse.contents = NSColor(calibratedHue: 0.6, saturation: 0.1, brightness: 0.95, alpha: 0.5)
        case .ceramic:
            mat.lightingModel = .phong; mat.specular.contents = NSColor(white: 0.8, alpha: 1.0); mat.shininess = 70.0
        case .carbon:
            mat.lightingModel = .physicallyBased; mat.metalness.contents = 0.1; mat.roughness.contents = 0.6; mat.diffuse.contents = NSColor(white: 0.15, alpha: 1.0)
        }
        mat.locksAmbientWithDiffuse = true
        return mat
    }
    
    private func createTubeGeometry(for path: [simd_float3], radius: Float, segments: Int) -> SCNGeometry? {
        let pointCount = path.count
        if pointCount < 2 { return nil }
        
        var vertices: [SCNVector3] = []; var normals: [SCNVector3] = []; var indices: [Int32] = []
        vertices.reserveCapacity(pointCount * segments)
        normals.reserveCapacity(pointCount * segments)
        indices.reserveCapacity(pointCount * segments * 6)
        
        var T = simd_normalize(path[1] - path[0])
        var N = simd_float3(0, 1, 0)
        if abs(simd_dot(T, N)) > 0.99 { N = simd_float3(1, 0, 0) }
        N = simd_normalize(simd_cross(T, N))
        var B = simd_cross(T, N)
        
        for i in 0..<pointCount {
            if i > 0 {
                let newT = simd_normalize(path[i] - path[i-1])
                let axis = simd_cross(T, newT)
                let len = simd_length(axis)
                if len > 0.0001 {
                    let angle = acos(min(max(simd_dot(T, newT), -1.0), 1.0))
                    let q = simd_quatf(angle: angle, axis: axis / len)
                    N = q.act(N); B = q.act(B)
                }
                T = newT
            }
            
            for j in 0..<segments {
                let angle = Float(j) / Float(segments) * Float.pi * 2
                let cosA = cos(angle); let sinA = sin(angle)
                let normal = simd_normalize(N * cosA + B * sinA)
                let pos = path[i] + normal * radius
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
        
        let sourceGeo = SCNGeometrySource(vertices: vertices)
        let sourceNorm = SCNGeometrySource(normals: normals)
        let element = SCNGeometryElement(indices: indices, primitiveType: .triangles)
        
        return SCNGeometry(sources: [sourceGeo, sourceNorm], elements: [element])
    }
}
