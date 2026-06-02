import SwiftUI
import SceneKit
import simd

// MARK: - SCNVector3 operators

extension SCNVector3 {
    static func +(lhs: SCNVector3, rhs: SCNVector3) -> SCNVector3 {
        SCNVector3(lhs.x + rhs.x, lhs.y + rhs.y, lhs.z + rhs.z)
    }
    static func -(lhs: SCNVector3, rhs: SCNVector3) -> SCNVector3 {
        SCNVector3(lhs.x - rhs.x, lhs.y - rhs.y, lhs.z - rhs.z)
    }
    static func *(vector: SCNVector3, scalar: Float) -> SCNVector3 {
        SCNVector3(vector.x * scalar, vector.y * scalar, vector.z * scalar)
    }
    static func *(scalar: Float, vector: SCNVector3) -> SCNVector3 { vector * scalar }
    static func +=(lhs: inout SCNVector3, rhs: SCNVector3) { lhs = lhs + rhs }
    func normalized() -> SCNVector3 {
        let len = sqrt(x*x + y*y + z*z)
        guard len > 0 else { return self }
        return SCNVector3(x/len, y/len, z/len)
    }
}

// MARK: - CustomSCNView (iOS touch handling)

class CustomSCNView: SCNView {
    var cameraDistance: Float = 5.0
    var cameraTheta: Float = 45.0
    var cameraPhi: Float = 30.0
    var cameraTarget: SCNVector3 = SCNVector3(0, 0, 0)

    weak var cameraNode: SCNNode?

    // Gesture state
    private var lastPanLocation: CGPoint = .zero
    private var isPanning = false
    private var lastTwoFingerLocation: CGPoint = .zero
    private var lastPinchScale: CGFloat = 1.0

    override init(frame: CGRect, options: [String: Any]? = nil) {
        super.init(frame: frame, options: options)
        setupGestures()
    }
    
    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setupGestures()
    }

    private func setupGestures() {
        // One finger: orbit
        let orbit = UIPanGestureRecognizer(target: self, action: #selector(handleOrbit(_:)))
        orbit.minimumNumberOfTouches = 1
        orbit.maximumNumberOfTouches = 1
        addGestureRecognizer(orbit)

        // Two fingers: pan
        let pan = UIPanGestureRecognizer(target: self, action: #selector(handlePan(_:)))
        pan.minimumNumberOfTouches = 2
        pan.maximumNumberOfTouches = 2
        addGestureRecognizer(pan)

        // Pinch: zoom
        let pinch = UIPinchGestureRecognizer(target: self, action: #selector(handlePinch(_:)))
        addGestureRecognizer(pinch)
    }

    @objc private func handleOrbit(_ gr: UIPanGestureRecognizer) {
        let loc = gr.location(in: self)
        if gr.state == .began {
            lastPanLocation = loc
        } else if gr.state == .changed {
            let dx = Float(loc.x - lastPanLocation.x)
            let dy = Float(loc.y - lastPanLocation.y)
            cameraTheta += dx * 0.3
            cameraPhi   += dy * 0.3
            cameraPhi = max(-89, min(89, cameraPhi))
            cameraTheta = fmod(cameraTheta, 360.0)
            if cameraTheta < 0 { cameraTheta += 360.0 }
            updateCameraTransform()
            lastPanLocation = loc
        }
    }

    @objc private func handlePan(_ gr: UIPanGestureRecognizer) {
        let loc = gr.location(in: self)
        if gr.state == .began {
            lastTwoFingerLocation = loc
        } else if gr.state == .changed {
            guard let cameraNode = cameraNode else { return }
            let dx = Float(loc.x - lastTwoFingerLocation.x)
            let dy = Float(loc.y - lastTwoFingerLocation.y)
            let right = SCNVector3(cameraNode.simdWorldRight)
            let up    = SCNVector3(cameraNode.simdWorldUp)
            let panSpeed = cameraDistance * 0.002
            cameraTarget = cameraTarget - (right * dx * panSpeed) + (up * dy * panSpeed)
            updateCameraTransform()
            lastTwoFingerLocation = loc
        }
    }

    @objc private func handlePinch(_ gr: UIPinchGestureRecognizer) {
        if gr.state == .began {
            lastPinchScale = gr.scale
        } else if gr.state == .changed {
            let delta = Float(gr.scale / lastPinchScale)
            cameraDistance /= delta
            cameraDistance = max(0.5, min(10000, cameraDistance))
            updateCameraTransform()
            lastPinchScale = gr.scale
        }
    }

    func updateCameraTransform() {
        guard let cameraNode = cameraNode else { return }
        let thetaRad = cameraTheta * .pi / 180.0
        let phiRad   = cameraPhi   * .pi / 180.0
        let x = cameraDistance * cos(thetaRad) * cos(phiRad)
        let y = cameraDistance * sin(phiRad)
        let z = cameraDistance * sin(thetaRad) * cos(phiRad)
        cameraNode.position = SCNVector3(x, y, z) + cameraTarget
        cameraNode.look(at: cameraTarget, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 0, -1))
    }

    func setCamera(distance: Float, theta: Float, phi: Float, target: SCNVector3) {
        cameraDistance = distance
        cameraTheta    = theta
        cameraPhi      = phi
        cameraTarget   = target
        updateCameraTransform()
    }
}

// MARK: - Coordinator

class GCodeSceneCoordinator: NSObject {
    weak var sceneView: CustomSCNView?
    var lastRenderTrigger: Int = -1
    var lastLightingTrigger: Int = -1
    var maxDimension: CGFloat = 100.0
    var modelCenterY: CGFloat = 0.0
}

// MARK: - GCodeSceneView (UIViewRepresentable)

struct GCodeSceneView: UIViewRepresentable {
    @EnvironmentObject var appState: AppState

    func makeCoordinator() -> GCodeSceneCoordinator { GCodeSceneCoordinator() }

    func makeUIView(context: Context) -> CustomSCNView {
        let view = CustomSCNView(frame: .zero)
        view.autoenablesDefaultLighting = false
        view.backgroundColor = .black
        view.isJitteringEnabled = true
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

    func updateUIView(_ uiView: CustomSCNView, context: Context) {
        if context.coordinator.lastRenderTrigger != appState.renderTrigger {
            context.coordinator.lastRenderTrigger = appState.renderTrigger
            rebuildScene(nsView: uiView, coordinator: context.coordinator)
            if appState.shouldResetCamera {
                appState.shouldResetCamera = false
                DispatchQueue.main.async {
                    self.setCameraToFront(nsView: uiView, coordinator: context.coordinator)
                }
            }
        }
        if context.coordinator.lastLightingTrigger != appState.lightingTrigger {
            context.coordinator.lastLightingTrigger = appState.lightingTrigger
            updateLighting(in: uiView)
        }
        uiView.scene?.rootNode.childNode(withName: "grid", recursively: false)?.isHidden = !appState.showAxis
        handleCameraAction(nsView: uiView, coordinator: context.coordinator)
    }

    // MARK: - Camera setup

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

    private func setCameraToFront(nsView: CustomSCNView, coordinator: GCodeSceneCoordinator) {
        let fovRad = nsView.pointOfView?.camera?.fieldOfView ?? 45.0
        let fovRadRad = fovRad * .pi / 180.0
        let distance = CGFloat(Float(coordinator.maxDimension)) * 1.3 / tan(fovRadRad / 2.0)
        let halfH = Float(coordinator.modelCenterY)
        nsView.setCamera(distance: Float(distance), theta: 0, phi: 0, target: SCNVector3(0, halfH, 0))
    }

    // MARK: - Lighting

    private func setupLighting(in view: CustomSCNView) {
        guard let root = view.scene?.rootNode else { return }

        let ambient = SCNLight(); ambient.type = .ambient; ambient.name = "ambientLight"
        ambient.color = UIColor(white: 1.0, alpha: 1.0)
        ambient.intensity = CGFloat(appState.lightingAmbient * 1000)
        let ambientNode = SCNNode(); ambientNode.name = "ambientLight"; ambientNode.light = ambient
        root.addChildNode(ambientNode)

        let main = SCNLight(); main.type = .directional; main.name = "mainLight"
        main.color = UIColor.white
        main.intensity = CGFloat(appState.lightingMainIntensity * 1000)
        let mainNode = SCNNode(); mainNode.name = "mainLight"; mainNode.light = main
        root.addChildNode(mainNode)

        let fill = SCNLight(); fill.type = .directional; fill.name = "fillLight"
        fill.color = UIColor(red: 0.8, green: 0.85, blue: 1.0, alpha: 1.0)
        fill.intensity = CGFloat(appState.lightingFillIntensity * 1000)
        let fillNode = SCNNode(); fillNode.name = "fillLight"; fillNode.light = fill
        root.addChildNode(fillNode)

        let rim = SCNLight(); rim.type = .directional; rim.name = "rimLight"
        rim.color = UIColor(red: 0.2, green: 0.25, blue: 0.4, alpha: 1.0)
        rim.intensity = 200
        let rimNode = SCNNode(); rimNode.name = "rimLight"; rimNode.light = rim
        rimNode.look(at: SCNVector3(0,0,0), up: SCNVector3(0,1,0), localFront: SCNVector3(0,0,-1))
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
        node.position = SCNVector3(cos(hRad)*cos(vRad)*dist, sin(vRad)*dist, sin(hRad)*cos(vRad)*dist*0.3)
        node.look(at: SCNVector3(0,0,0), up: SCNVector3(0,1,0), localFront: SCNVector3(0,0,-1))
    }

    private func positionFillLight(_ node: SCNNode) {
        let dist: Float = 2000
        let hRad = (appState.lightingAngleH + 270) * .pi / 180
        let vRad = Float(-15) * .pi / 180
        node.position = SCNVector3(cos(hRad)*cos(vRad)*dist, sin(vRad)*dist, sin(hRad)*cos(vRad)*dist*0.3)
        node.look(at: SCNVector3(0,0,0), up: SCNVector3(0,1,0), localFront: SCNVector3(0,0,-1))
    }

    // MARK: - Camera actions

    private func handleCameraAction(nsView: CustomSCNView, coordinator: GCodeSceneCoordinator) {
        guard appState.cameraAction != .none else { return }
        defer { appState.cameraAction = .none }

        if appState.cameraAction == .rotate360 {
            if let root = nsView.scene?.rootNode.childNode(withName: "gcode_container", recursively: false) {
                root.removeAllActions()
                root.runAction(SCNAction.rotateBy(x: 0, y: CGFloat(Float.pi * 2), z: 0, duration: 3.0))
            }
            return
        }

        let fovRad = nsView.pointOfView?.camera?.fieldOfView ?? 45.0
        let fovRadRad = fovRad * .pi / 180.0
        let distance = CGFloat(Float(coordinator.maxDimension)) * 1.3 / tan(fovRadRad / 2.0)
        let halfH = Float(coordinator.modelCenterY)
        let target = SCNVector3(0, halfH, 0)

        var theta: Float = 0; var phi: Float = 0; var dist = distance

        switch appState.cameraAction {
        case .front:  theta = 0;   phi = 0;   dist = distance * 0.8
        case .back:   theta = 180; phi = 0
        case .left:   theta = -90; phi = 0
        case .right:  theta = 90;  phi = 0
        case .top:    theta = 0;   phi = 90;  dist = distance * 0.8
        case .bottom: theta = 0;   phi = -90; dist = distance * 0.8
        case .iso1:   theta = 45;  phi = 30
        case .iso2:   theta = -45; phi = 30
        case .iso3:   theta = 45;  phi = -30
        case .iso4:   theta = -45; phi = -30
        default: break
        }
        nsView.setCamera(distance: Float(dist), theta: theta, phi: phi, target: target)
    }

    // MARK: - Scene rebuild

    private func rebuildScene(nsView: CustomSCNView, coordinator: GCodeSceneCoordinator) {
        let startTime = CFAbsoluteTimeGetCurrent()
        nsView.scene?.rootNode.childNodes.filter { $0.name == "gcode_container" }.forEach { $0.removeFromParentNode() }
        guard !appState.loadedModels.isEmpty else { return }

        let containerNode = SCNNode(); containerNode.name = "gcode_container"
        let material = getMaterial(preset: appState.selectedMaterial, color: UIColor(appState.modelColor))

        var allMinX: Float = .greatestFiniteMagnitude, allMaxX: Float = -.greatestFiniteMagnitude
        var allMinY: Float = .greatestFiniteMagnitude, allMaxY: Float = -.greatestFiniteMagnitude
        var allMinZ: Float = .greatestFiniteMagnitude, allMaxZ: Float = -.greatestFiniteMagnitude

        for model in appState.loadedModels where model.isVisible {
            guard !model.processedLayers.isEmpty else { continue }
            let modelNode = SCNNode(); modelNode.name = "model_\(model.id.uuidString)"

            for layerData in model.processedLayers {
                let geo = SCNGeometry(
                    sources: [SCNGeometrySource(vertices: layerData.vertices),
                              SCNGeometrySource(normals: layerData.normals)],
                    elements: [SCNGeometryElement(indices: layerData.indices, primitiveType: .triangles)]
                )
                geo.materials = [material]
                let layerNode = SCNNode(geometry: geo); layerNode.name = "layer_\(layerData.id)"
                modelNode.addChildNode(layerNode)
            }

            modelNode.position = SCNVector3(model.position.x, model.position.y, model.position.z)

            if let bbox = model.boundingBox {
                allMinX = min(allMinX, bbox.min.x + model.position.x)
                allMaxX = max(allMaxX, bbox.max.x + model.position.x)
                allMinY = min(allMinY, bbox.min.y + model.position.y)
                allMaxY = max(allMaxY, bbox.max.y + model.position.y)
                allMinZ = min(allMinZ, bbox.min.z + model.position.z)
                allMaxZ = max(allMaxZ, bbox.max.z + model.position.z)
            }
            containerNode.addChildNode(modelNode)
        }

        nsView.scene?.rootNode.addChildNode(containerNode)

        if allMinX != .greatestFiniteMagnitude {
            let sX = allMaxX - allMinX, sY = allMaxY - allMinY, sZ = allMaxZ - allMinZ
            coordinator.maxDimension = CGFloat(max(sqrt(sX*sX + sY*sY + sZ*sZ) / 2, 1))
            coordinator.modelCenterY = CGFloat((allMinY + allMaxY) / 2)
        }

        nsView.scene?.rootNode.childNode(withName: "grid", recursively: false)?.removeFromParentNode()
        let gridNode = createGridNode(maxDimension: coordinator.maxDimension)
        gridNode.isHidden = !appState.showAxis
        nsView.scene?.rootNode.addChildNode(gridNode)

        if let cameraNode = nsView.scene?.rootNode.childNode(withName: "mainCamera", recursively: false) {
            nsView.cameraNode = cameraNode
            let target = SCNVector3(0, Float(coordinator.modelCenterY), 0)
            nsView.setCamera(distance: nsView.cameraDistance, theta: nsView.cameraTheta,
                             phi: nsView.cameraPhi, target: target)
        }

        appState.log("⏱ 3D Scene Render: \(String(format: "%.2f", (CFAbsoluteTimeGetCurrent() - startTime) * 1000)) ms")
    }

    // MARK: - Grid & Axis

    private func createGridNode(maxDimension: CGFloat) -> SCNNode {
        let gridNode = SCNNode(); gridNode.name = "grid"
        let steps: [CGFloat] = [10, 50, 100, 500, 1000, 5000]
        let idealStep = maxDimension * 2.0 / 10.0
        var step = steps.last!
        for s in steps { if idealStep <= s { step = s; break } }
        let halfExtent = maxDimension

        var vertices: [SCNVector3] = []; var indices: [Int32] = []; var idx: Int32 = 0
        var z = -halfExtent
        while z <= halfExtent + 0.001 {
            vertices.append(SCNVector3(-halfExtent, 0, z)); vertices.append(SCNVector3(halfExtent, 0, z))
            indices.append(idx); indices.append(idx+1); idx += 2; z += step
        }
        var x = -halfExtent
        while x <= halfExtent + 0.001 {
            vertices.append(SCNVector3(x, 0, -halfExtent)); vertices.append(SCNVector3(x, 0, halfExtent))
            indices.append(idx); indices.append(idx+1); idx += 2; x += step
        }

        let gridGeo = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices)],
                                  elements: [SCNGeometryElement(indices: indices, primitiveType: .line)])
        let gridMat = SCNMaterial(); gridMat.diffuse.contents = UIColor.gray; gridMat.lightingModel = .constant
        gridGeo.materials = [gridMat]
        gridNode.addChildNode(SCNNode(geometry: gridGeo))

        let axisLen = maxDimension * 1.2; let axisRadius = maxDimension * 0.005; let offset = axisLen * 0.05

        func addAxis(color: UIColor, eulerX: Float, eulerZ: Float, position: SCNVector3, label: String, labelPos: SCNVector3) {
            let geo = SCNCylinder(radius: axisRadius, height: axisLen)
            geo.materials = [axisMaterial(color: color)]
            let node = SCNNode(geometry: geo)
            node.eulerAngles = SCNVector3(eulerX, 0, eulerZ); node.position = position
            gridNode.addChildNode(node)
            gridNode.addChildNode(textNode(label, position: labelPos, color: color))
        }

        addAxis(color: .red, eulerX: 0, eulerZ: Float.pi/2,
                position: SCNVector3(axisLen/2, 0, 0), label: "X", labelPos: SCNVector3(axisLen + offset, 0, 0))
        addAxis(color: .green, eulerX: 0, eulerZ: 0,
                position: SCNVector3(0, axisLen/2, 0), label: "Y", labelPos: SCNVector3(0, axisLen + offset, 0))
        addAxis(color: .blue, eulerX: Float.pi/2, eulerZ: 0,
                position: SCNVector3(0, 0, axisLen/2), label: "Z", labelPos: SCNVector3(0, 0, axisLen + offset))
        gridNode.addChildNode(textNode("0", position: SCNVector3(offset, 0, 0), color: .gray))

        return gridNode
    }

    private func textNode(_ string: String, position: SCNVector3, color: UIColor) -> SCNNode {
        let text = SCNText(string: string, extrusionDepth: 0.1)
        text.font = UIFont.systemFont(ofSize: 1.0); text.flatness = 0.1
        let mat = SCNMaterial(); mat.diffuse.contents = color; mat.lightingModel = .constant
        text.materials = [mat]
        let node = SCNNode(geometry: text); node.position = position
        let scale = CGFloat(max(appState.modelSize.x, 1)) * 0.05
        node.scale = SCNVector3(scale, scale, scale)
        return node
    }

    private func axisMaterial(color: UIColor) -> SCNMaterial {
        let mat = SCNMaterial(); mat.diffuse.contents = color; mat.lightingModel = .constant; return mat
    }

    private func getMaterial(preset: MaterialPreset, color: UIColor) -> SCNMaterial {
        let mat = SCNMaterial(); mat.diffuse.contents = color
        switch preset {
        case .matte:
            mat.lightingModel = .lambert; mat.specular.contents = UIColor.black
        case .plastic:
            mat.lightingModel = .phong
            mat.specular.contents = UIColor(white: 0.5, alpha: 1.0); mat.shininess = 40.0
        case .steel:
            mat.lightingModel = .physicallyBased; mat.metalness.contents = 1.0; mat.roughness.contents = 0.35
        case .glass:
            mat.lightingModel = .physicallyBased; mat.metalness.contents = 0.0; mat.roughness.contents = 0.05
            mat.transparency = 0.4
            mat.diffuse.contents = UIColor(hue: 0.6, saturation: 0.1, brightness: 0.95, alpha: 0.5)
        }
        mat.locksAmbientWithDiffuse = true
        return mat
    }
}
