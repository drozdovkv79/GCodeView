import SwiftUI
import UniformTypeIdentifiers
import SceneKit

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        NavigationSplitView {
            leftPanel
        } content: {
            GCodeSceneView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } detail: {
            rightPanel
        }
    }
    
    private var leftPanel: some View {
        ScrollView {
            VStack(spacing: 15) {
                
                HStack {
                    Image(systemName: "folder").foregroundColor(.secondary)
                    Text(appState.currentDirectory?.lastPathComponent ?? "Select Directory")
                        .lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Button("Browse") { selectDirectory() }.buttonStyle(.bordered)
                }
                
                // Таблица файлов
                VStack(spacing: 0) {
                    HStack(spacing: 5) {
                        sortButton(title: "Name", order: .name)
                        sortButton(title: "Size", order: .size)
                        sortButton(title: "Date", order: .date)
                    }
                    .padding(5)
                    .background(Color(NSColor.controlBackgroundColor))
                    
                    List(appState.sortedFiles, id: \.id, selection: $appState.selectedFileURL) { item in
                        HStack(spacing: 5) {
                            Text(item.name).frame(maxWidth: .infinity, alignment: .leading)
                            Text(item.formattedSize).frame(width: 60, alignment: .trailing).font(.caption).foregroundColor(.secondary)
                            Text(item.formattedDate).frame(width: 90, alignment: .trailing).font(.caption).foregroundColor(.secondary)
                        }
                        .tag(item.url)
                    }
                    .listStyle(.plain)
                    .frame(height: 260)
                }
                .border(Color.gray.opacity(0.3))
                
                HStack {
                    Button(action: { appState.loadSelectedFile() }) {
                        Text(appState.isLoading ? "Loading..." : "Load Model").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(appState.selectedFileURL == nil || appState.isLoading)
                    
                    Button(action: { appState.cameraAction = .rotate360 }) {
                        Image(systemName: "arrow.triangle.2.circlepath")
                    }
                    .buttonStyle(.bordered)
                    .disabled(appState.rawPoints.isEmpty)
                    
                    Button(action: { recordVideo() }) {
                        Image(systemName: appState.isRecording ? "stop.circle" : "record.circle")
                    }
                    .buttonStyle(.bordered)
                    .disabled(appState.rawPoints.isEmpty || appState.isRecording)
                    .foregroundColor(appState.isRecording ? .red : .primary)
                }
                
                if appState.isLoading { ProgressView(value: appState.progress, total: 100.0) }
                
                DisclosureGroup("Camera Views") { cameraViewsContent }
                DisclosureGroup("Materials") { materialsContent }
                DisclosureGroup("Parameters") { parametersContent }
            }
            .padding()
        }
    }
    
    private func sortButton(title: String, order: SortOrder) -> some View {
        Button(action: { appState.sortOrder = order }) {
            Text(title)
                .font(.caption)
                .fontWeight(appState.sortOrder == order ? .bold : .regular)
                .foregroundColor(appState.sortOrder == order ? .blue : .secondary)
        }
        .buttonStyle(.plain)
    }
    
    private var cameraViewsContent: some View {
        VStack(spacing: 10) {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 5) {
                CamButton(title: "Top", action: .top); CamButton(title: "Bottom", action: .bottom)
                CamButton(title: "Front", action: .front); CamButton(title: "Back", action: .back)
                CamButton(title: "Left", action: .left); CamButton(title: "Right", action: .right)
                CamButton(title: "ISO 1", action: .iso1); CamButton(title: "ISO 2", action: .iso2)
                CamButton(title: "ISO 3", action: .iso3); CamButton(title: "ISO 4", action: .iso4)
            }
        }
    }
    
    private var materialsContent: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 5) {
            ForEach(MaterialPreset.allCases, id: \.self) { mat in
                if appState.selectedMaterial == mat {
                    Button(mat.rawValue) { appState.changeMaterial(mat) }.buttonStyle(.borderedProminent)
                } else {
                    Button(mat.rawValue) { appState.changeMaterial(mat) }.buttonStyle(.bordered)
                }
            }
        }
    }
    
    private var parametersContent: some View {
        VStack {
            Text("Tube Diameter (mm)")
            HStack {
                Slider(value: $appState.tempTubeDiameter, in: 1.0...10.0, step: 0.5)
                Text(String(format: "%.1f", appState.tempTubeDiameter)).frame(width: 35)
            }
            Button("Apply Diameter") { appState.applyDiameter() }.disabled(appState.rawPoints.isEmpty)
            Divider().padding(.vertical, 5)
            ColorPicker("Pick Color", selection: $appState.tempModelColor)
            Button("Apply Color") { appState.applyColor() }.disabled(appState.rawPoints.isEmpty)
        }
    }
    
    private var rightPanel: some View {
        TabView { analyticsTab; logTab }
    }
    
    private var analyticsTab: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                if let stats = appState.stats { analyticsContent(stats: stats) } else { Text("No data.") }
            }.padding()
        }.tabItem { Label("Analytics", systemImage: "chart.bar") }
    }
    
    private func analyticsContent(stats: GCodeStats) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Group {
                Text("=== GCODE ANALYSIS ===").font(.headline)
                Text("1. Points: Total \(stats.totalPoints), Ext \(stats.extrusionPoints), Trav \(stats.travelPoints)")
                Text("2. Dim: W\(String(format:"%.1f", stats.width)) L\(String(format:"%.1f", stats.length)) H\(String(format:"%.1f", stats.height)) mm")
                Text("3. Layers: \(stats.numLayers)"); Text("4. Material: \(String(format:"%.1f", stats.totalMaterial)) mm")
                Text("5. Volume: \(String(format:"%.1f", stats.volume)) mm³")
                Text("6. Extremes: MaxZ \(String(format:"%.1f", stats.maxZ)), MaxSpd \(String(format:"%.0f", stats.maxSpeed))")
            }
            Divider()
            Group {
                Text("=== EXTENDED MATH ===").font(.headline)
                Text("7. Ext Path: \(String(format:"%.1f", stats.extrusionPathLength)) mm")
                Text("8. Travel Path: \(String(format:"%.1f", stats.travelPathLength)) mm")
                Text("9. Est. Time: \(String(format:"%.1f", stats.estimatedPrintTimeMin)) min")
                Text("10. Avg Flow: \(String(format:"%.3f", stats.averageFlowRate)) mm³/mm")
                Text("11. BBox Vol: \(String(format:"%.1f", stats.boundingBoxVolume)) mm³")
                Text("12. XY Area: \(String(format:"%.1f", stats.xyFootprintArea)) mm²")
                Text("13. CoM: X\(String(format:"%.1f", stats.centerOfMassX)) Y\(String(format:"%.1f", stats.centerOfMassY))")
                Text("14. Sharp Corners: \(stats.sharpCornersCount)")
                Text("15. Compactness: \(String(format:"%.4f", stats.modelCompactness))")
            }
            Divider()
            Group {
                Text("=== OPTIMIZATION ===").font(.headline)
                Text("Original ext pts: \(stats.originalExtrusionPoints)")
                Text("Optimized ext pts: \(stats.optimizedExtrusionPoints)")
                Text("Reduction: \(String(format: "%.1f", stats.optimizationReductionPercent))%")
            }
        }
    }
    
    private var logTab: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(appState.logMessages, id: \.self) { msg in Text(msg).font(.system(.caption, design: .monospaced)) }
            }.padding()
        }.tabItem { Label("Log", systemImage: "terminal") }
    }
    
    // MARK: - Logic
    private func selectDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            appState.currentDirectory = url
            appState.log("Selected directory: \(url.path)")
            do {
                let urls = try FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey])
                var items: [FileItem] = []
                for fileURL in urls {
                    let ext = fileURL.pathExtension.lowercased()
                    guard ext == "gcode" || ext == "nc" || ext == "ngc" else { continue }
                    let resources = try fileURL.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                    let item = FileItem(
                        url: fileURL,
                        name: fileURL.lastPathComponent,
                        size: Int64(resources.fileSize ?? 0),
                        date: resources.contentModificationDate ?? Date.distantPast
                    )
                    items.append(item)
                }
                DispatchQueue.main.async {
                    appState.fileItems = items
                    appState.selectedFileURL = nil
                    appState.log("Found \(items.count) GCode files.")
                }
            } catch { appState.log("Error reading directory: \(error)") }
        }
    }
    
    private func recordVideo() {
        appState.isRecording = true
        appState.cameraAction = .rotate360
        appState.log("Starting 360° video recording...")
        
        // Даем время анимации начаться
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            guard let sceneView = (NSApp.windows.first?.contentView?.subviews.first(where: { $0 is SCNView })) as? SCNView else {
                appState.isRecording = false; return
            }
            
            DispatchQueue.global(qos: .userInitiated).async {
                var frames: [CGImage] = []
                let totalFrames = 90 // 3 секунды при 30 fps
                
                for i in 0..<totalFrames {
                    let time = TimeInterval(i) / 30.0
                    DispatchQueue.main.sync {
                        sceneView.scene?.rootNode.enumerateChildNodes { node, _ in
                            if node.name == "gcode" { node.removeAllActions() } // Останавливаем реальную анимацию
                        }
                        // Вручную крутим на нужный угол
                        if let rootNode = sceneView.scene?.rootNode.childNode(withName: "gcode", recursively: false) {
                            rootNode.eulerAngles.y = CGFloat(Float((time / 3.0) * 2 * .pi))
                        }
                        sceneView.frame = CGRect(x: 0, y: 0, width: 1920, height: 1080) // Фиксированный размер рендера
                        if let img = sceneView.snapshot().cgImage(forProposedRect: nil, context: nil, hints: nil) { frames.append(img) }
                        
                    }
                }
                
                // Сохраняем GIF на рабочий стол
                DispatchQueue.main.async {
                    saveFramesAsGIF(frames: frames)
                    appState.isRecording = false
                    appState.log("Video saved to Desktop as GCode_Rotation.gif")
                }
            }
        }
    }
    
    private func saveFramesAsGIF(frames: [CGImage]) {
        guard !frames.isEmpty else { return }
        let desktopURL = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first!
        let fileURL = desktopURL.appendingPathComponent("GCode_Rotation.gif")
        
        let destination = CGImageDestinationCreateWithURL(fileURL as CFURL, kUTTypeGIF, frames.count, nil)!
        let properties = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: 1.0/30.0]] as CFDictionary
        
        for frame in frames {
            CGImageDestinationAddImage(destination, frame, properties)
        }
        CGImageDestinationFinalize(destination)
    }
}

struct CamButton: View {
    var title: String
    var action: CameraAction
    @EnvironmentObject var appState: AppState
    var body: some View {
        Button(title) { appState.cameraAction = action }.buttonStyle(.bordered)
    }
}
