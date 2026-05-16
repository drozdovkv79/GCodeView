import SwiftUI
import SceneKit

struct GCodeSceneView: NSViewRepresentable {
    @EnvironmentObject var appState: AppState
    
    func makeNSView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = NSColor(calibratedWhite: 0.1, alpha: 1.0)
        view.scene = SCNScene()
        
        // Camera setup
        let cameraNode = SCNNode()
        cameraNode.camera = SCNCamera()
        cameraNode.position = SCNVector3(x: 0, y: 0, z: 100)
        view.scene?.rootNode.addChildNode(cameraNode)
        
        return view
    }
    
    func updateNSView(_ nsView: SCNView, context: Context) {
        guard !appState.points.isEmpty else { return }
        
        // Clear old nodes
        nsView.scene?.rootNode.childNodes.filter { $0.name == "gcode" }.forEach { $0.removeFromParentNode() }
        
        let rootNode = SCNNode()
        rootNode.name = "gcode"
        
        let extPts = appState.points.filter { $0.isExtrusion }
        let radius = CGFloat(appState.tubeDiameter / 2.0)
        let color = NSColor(appState.modelColor)
        
        var prevPoint: GCodePoint? = nil
        
        for point in extPts {
            if let prev = prevPoint, prev.layer == point.layer {
                let p1 = SCNVector3(prev.x, prev.z, prev.y) // Y is up in SceneKit
                let p2 = SCNVector3(point.x, point.z, point.y)
                
                let distance = CGFloat(SCNVector3Distance(from: p1, to: p2))
                if distance < 0.001 { continue }
                
                // Equivalent to vtkTubeFilter
                let cylinder = SCNCylinder(radius: radius, height: distance)
                cylinder.radialSegmentCount = 8
                
                let material = SCNMaterial()
                material.diffuse.contents = color
                material.lightingModel = .phong
                cylinder.materials = [material]
                
                let node = SCNNode(geometry: cylinder)
                node.position = SCNVector3(
                    (p1.x + p2.x) / 2,
                    (p1.y + p2.y) / 2,
                    (p1.z + p2.z) / 2
                )
                node.eulerAngles = SCNVector3(
                    Float.pi / 2, 
                    0, 
                    -atan2(p2.z - p1.z, p2.x - p1.x)
                )
                
                rootNode.addChildNode(node)
            }
            prevPoint = point
        }
        
        // Center model
        let boundingBox = rootNode.boundingBox
        let dx = (boundingBox.min.x + boundingBox.max.x) / 2
        let dy = (boundingBox.min.y + boundingBox.max.y) / 2
        let dz = (boundingBox.min.z + boundingBox.max.z) / 2
        rootNode.position = SCNVector3(-dx, -dy, -dz)
        
        nsView.scene?.rootNode.addChildNode(rootNode)
    }
}

func SCNVector3Distance(from: SCNVector3, to: SCNVector3) -> Float {
    return sqrt(pow(to.x - from.x, 2) + pow(to.y - from.y, 2) + pow(to.z - from.z, 2))
}

extension Color {
    init?(hex: String) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")
        var rgb: UInt64 = 0
        Scanner(string: hexSanitized).scanHexInt64(&rgb)
        self.init(
            red: Double((rgb & 0xFF0000) >> 16) / 255.0,
            green: Double((rgb & 0x00FF00) >> 8) / 255.0,
            blue: Double(rgb & 0x0000FF) / 255.0
        )
    }
}