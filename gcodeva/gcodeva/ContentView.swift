import SwiftUI
import UniformTypeIdentifiers
import AVFoundation
import SceneKit // Добавлен импорт для SCNView

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
                
                VStack(spacing: 0) {
                    HStack(spacing: 5) {
                        sortButton(title: "Name", order: .name)
                        sortButton(title: "Size", order: .size)
                        sortButton(title: "Date", order: .date)
                    }
                    .padding(5).background(Color(NSColor.controlBackgroundColor))
                    
                    List(appState.sortedFiles, id: \.id, selection: $appState.selectedFileURL) { item in
                        HStack(spacing: 5) {
                            Text(item.name).frame(maxWidth: .infinity, alignment: .leading)
                            Text(item.formattedSize).frame(width: 60, alignment: .trailing).font(.caption).foregroundColor(.secondary)
                            Text(item.formattedDate).frame(width: 70, alignment: .trailing).font(.caption).foregroundColor(.secondary)
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
                }
                
                if appState.isLoading { ProgressView(value: appState.progress, total: 100.0) }
                
                DisclosureGroup("Camera Views") { cameraViewsContent }
                DisclosureGroup("Export") { exportContent }
                DisclosureGroup("Materials") { materialsContent }
                DisclosureGroup("Parameters") { parametersContent }
            }
            .padding()
        }
    }
    
    private func sortButton(title: String, order: SortOrder) -> some View {
        Button(action: { appState.sortOrder = order }) {
            Text(title).font(.caption)
                .fontWeight(appState.sortOrder == order ? .bold : .regular)
                .foregroundColor(appState.sortOrder == order ? .blue : .secondary)
        }.buttonStyle(.plain)
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
            Button("Rotate 360°") { appState.cameraAction = .rotate360 }
                .buttonStyle(.bordered).frame(maxWidth: .infinity)
            Toggle("Show Axis & Grid", isOn: $appState.showAxis)
                            .toggleStyle(.checkbox)
        }
    }
    
    // Блок экспорта
    private var exportContent: some View {
        VStack(spacing: 10) {
            Button(action: { recordVideo() }) {
                HStack {
                    Image(systemName: appState.isRecording ? "stop.circle" : "video")
                    Text(appState.isRecording ? "Recording..." : "Record 360° Video (MP4)")
                }
            }
            .buttonStyle(.bordered)
            .disabled(appState.rawPoints.isEmpty || appState.isRecording)
            .foregroundColor(appState.isRecording ? .red : .primary)
            
            Button(action: { savePhotos() }) {
                HStack {
                    Image(systemName: "photo.on.rectangle")
                    Text("Save 10 View Photos")
                }
            }
            .buttonStyle(.bordered)
            .disabled(appState.rawPoints.isEmpty)
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
            appState.loadFilesFromDirectory(url)
        }
    }
    
    // MARK: - Save Photos
    private func savePhotos() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.prompt = "Choose folder to save photos"
        
        if panel.runModal() == .OK, let dir = panel.url {
            guard let sceneView = getSceneView() else { return }
            
            let views: [(String, CameraAction)] = [
                ("Front", .front), ("Back", .back), ("Left", .left), ("Right", .right),
                ("Top", .top), ("Bottom", .bottom),
                ("ISO_1", .iso1), ("ISO_2", .iso2), ("ISO_3", .iso3), ("ISO_4", .iso4)
            ]
            
            appState.log("Saving photos to \(dir.path)...")
            
            for (name, action) in views {
                // Принудительно меняем вид
                appState.cameraAction = action
                // Ждем обновления View (RunLoop)
                RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
                
                if let imgRep = sceneView.snapshot().tiffRepresentation,
                   let img = NSImage(data: imgRep) {
                    let fileURL = dir.appendingPathComponent("\(name).png")
                    if let tiffData = img.tiffRepresentation,
                       let bitmap = NSBitmapImageRep(data: tiffData),
                       let pngData = bitmap.representation(using: .png, properties: [:]) {
                        try? pngData.write(to: fileURL)
                    }
                }
            }
            appState.log("Photos saved successfully!")
        }
    }
    
    // MARK: - Record Video (MP4)
    private func recordVideo() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "mp4")!]
        panel.nameFieldStringValue = "GCode_Rotation.mp4"
        panel.prompt = "Save Video"
        
        guard panel.runModal() == .OK, let outputURL = panel.url else { return }
        
        guard let sceneView = getSceneView() else {
            appState.log("Error: Could not find 3D View for recording.")
            return
        }
        
        appState.isRecording = true
        appState.log("Preparing video recording...")
        
        DispatchQueue.global(qos: .userInitiated).async {
            let width = 1080
            let height = 1920
            let fps: Int32 = 30
            let duration: Double = 3.0
            let totalFrames = Int(Double(fps) * duration)
            
            do {
                let videoWriter = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
                let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: [
                    AVVideoCodecKey: AVVideoCodecType.h264,
                    AVVideoWidthKey: width,
                    AVVideoHeightKey: height
                ])
                let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: writerInput, sourcePixelBufferAttributes: [
                    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
                    kCVPixelBufferWidthKey as String: width,
                    kCVPixelBufferHeightKey as String: height
                ])
                
                videoWriter.add(writerInput)
                videoWriter.startWriting()
                videoWriter.startSession(atSourceTime: CMTime.zero)
                
                // 1. Создаем буфер один раз
                var pixelBuffer: CVPixelBuffer?
                let bufferAttrs: [String: Any] = [
                    kCVPixelBufferCGImageCompatibilityKey as String: true,
                    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
                ]
                CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32ARGB, bufferAttrs as CFDictionary, &pixelBuffer)
                
                guard let buffer = pixelBuffer else {
                    DispatchQueue.main.async { self.appState.isRecording = false }
                    return
                }
                
                // 2. Подготавливаем инструменты для рендеринга
                let ciContext = CIContext()
                let colorSpace = CGColorSpaceCreateDeviceRGB()
                let targetBounds = CGRect(x: 0, y: 0, width: width, height: height)
                
                // Черный фон для(letterbox), если пропорции окна не 16:9
                let blackBackground = CIImage(color: CIColor.black).cropped(to: targetBounds)
                
                var frameCount: Int64 = 0
                
                for i in 0..<totalFrames {
                    let time = Double(i) / Double(fps)
                    let angle = Float((time / duration) * 2 * .pi)
                    
                    var cgImg: CGImage?
                    DispatchQueue.main.sync {
                        if let rootNode = sceneView.scene?.rootNode.childNode(withName: "gcode", recursively: false) {
                            rootNode.removeAllActions()
                            rootNode.eulerAngles.y = CGFloat(angle)
                        }
                        let nsImage = sceneView.snapshot()
                        cgImg = nsImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
                    }
                    
                    if let image = cgImg {
                        let ciImage = CIImage(cgImage: image)
                        let extent = ciImage.extent
                        
                        // 3. Вычисляем масштаб для Aspect Fit (вписать целиком без обрезки)
                        let scaleX = CGFloat(width) / extent.width
                        let scaleY = CGFloat(height) / extent.height
                        let scale = min(scaleX, scaleY)
                        
                        // Масштабируем и центрируем картинку
                        var transformedImage = ciImage.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                        let scaledExtent = transformedImage.extent
                        let originX = (CGFloat(width) - scaledExtent.width) / 2.0
                        let originY = (CGFloat(height) - scaledExtent.height) / 2.0
                        transformedImage = transformedImage.transformed(by: CGAffineTransform(translationX: originX, y: originY))
                        
                        while !writerInput.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.01) }
                        let presentationTime = CMTimeMake(value: frameCount, timescale: fps)
                        
                        // 4. Сначала рисуем черный фон, затем поверх нашу модель
                        ciContext.render(blackBackground, to: buffer, bounds: targetBounds, colorSpace: colorSpace)
                        ciContext.render(transformedImage, to: buffer, bounds: targetBounds, colorSpace: colorSpace)
                        
                        adaptor.append(buffer, withPresentationTime: presentationTime)
                    }
                    frameCount += 1
                }
                
                writerInput.markAsFinished()
                videoWriter.finishWriting {
                    DispatchQueue.main.async {
                        self.appState.isRecording = false
                        if videoWriter.status == .completed {
                            self.appState.log("Video saved successfully to \(outputURL.path)")
                        } else {
                            self.appState.log("Video error: \(videoWriter.error?.localizedDescription ?? "Unknown")")
                        }
                    }
                }
                
            } catch {
                DispatchQueue.main.async {
                    self.appState.isRecording = false
                    self.appState.log("Video error: \(error.localizedDescription)")
                }
            }
        }
    }

    // Функция getSceneView больше не нужна, но если она осталась, замените её тело:
    private func getSceneView() -> SCNView? {
        // Надежный поиск SCNView через NSView иерархию окна
        guard let window = NSApp.windows.first,
              let contentView = window.contentView else { return nil }
        
        return findSCNView(in: contentView)
    }

    // Рекурсивный поиск нужного нам SCNView внутри иерархии AppKit
    private func findSCNView(in view: NSView) -> SCNView? {
        if let scnView = view as? SCNView {
            return scnView
        }
        for subview in view.subviews {
            if let found = findSCNView(in: subview) {
                return found
            }
        }
        return nil
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
