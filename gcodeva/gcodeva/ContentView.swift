import AVFoundation
import SceneKit
import SwiftUI
import UniformTypeIdentifiers
import MetalPerformanceShaders

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var isLeftPanelVisible = true
    @State private var isRightPanelVisible = true
    @State private var isFileBrowserExpanded = true

    var body: some View {
        HSplitView {
            if isLeftPanelVisible {
                leftPanel
                    .frame(minWidth: 200, maxWidth: 400)
            }
            centerPanel
                .frame(minWidth: 200)
            if isRightPanelVisible {
                rightPanel
                    .frame(minWidth: 200, maxWidth: 400)
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .navigation) {
                Button(action: { isLeftPanelVisible.toggle() }) {
                    Label(
                        isLeftPanelVisible ? "Hide Left" : "Show Left",
                        systemImage: "sidebar.left"
                    )
                }
                Button(action: { isRightPanelVisible.toggle() }) {
                    Label(
                        isRightPanelVisible ? "Hide Right" : "Show Right",
                        systemImage: "sidebar.right"
                    )
                }

                Button(action: { appState.showAxis.toggle() }) {
                    Label(
                        appState.showAxis ? "Hide Axis" : "Show Axis",
                        systemImage: "move.3d"
                    )
                }
            }
        }
        .onAppear {
            if appState.tempTubeDiameter == 0 {
                appState.tempTubeDiameter = 6.0
            }
        }
    }

    // MARK: - Левая панель

    private var leftPanel: some View {
        ScrollView {
            VStack(spacing: 15) {
                DisclosureGroup(isExpanded: $isFileBrowserExpanded) {
                    VStack(spacing: 15) {
                        HStack {
                            Image(systemName: "folder").foregroundColor(
                                .secondary
                            )
                            Text(
                                appState.currentDirectory?.lastPathComponent
                                    ?? "Select Directory"
                            )
                            .lineLimit(1).truncationMode(.middle)
                            Spacer()
                            Button("Browse") { selectDirectory() }.buttonStyle(
                                .bordered
                            )
                        }

                        VStack(spacing: 0) {
                            HStack(spacing: 5) {
                                sortButton(title: "Name", order: .name)
                                sortButton(title: "Size", order: .size)
                                sortButton(title: "Date", order: .date)
                            }
                            .padding(5)
                            .background(Color(NSColor.controlBackgroundColor))

                            List(
                                appState.sortedFiles,
                                id: \.url,
                                selection: $appState.selectedFileURL
                            ) { item in
                                HStack(spacing: 5) {
                                    Text(item.name).frame(
                                        maxWidth: .infinity,
                                        alignment: .leading
                                    )
                                    Text(item.formattedSize).frame(
                                        width: 60,
                                        alignment: .trailing
                                    ).font(.caption).foregroundColor(.secondary)
                                    Text(item.formattedDate).frame(
                                        width: 70,
                                        alignment: .trailing
                                    ).font(.caption).foregroundColor(.secondary)
                                }
                                .tag(item.url)
                            }
                            .listStyle(.plain)
                            .frame(height: 260)
                        }
                        .border(Color.gray.opacity(0.3))

                        Button(action: {
                            appState.loadSelectedFile()
                            appState.shouldResetCamera = true
                        }) {
                            Text(
                                appState.isLoading
                                    ? "Loading..." : "Load Model (Replace)"
                            ).frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(
                            appState.selectedFileURL == nil
                                || appState.isLoading
                        )

                        Button(action: { appState.addModel() }) {
                            Text(
                                appState.isLoading
                                    ? "Adding..." : "➕ Add Selected Model"
                            ).frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(
                            appState.selectedFileURL == nil
                                || appState.isLoading
                        )

                        if appState.isLoading {
                            ProgressView(value: appState.progress, total: 100.0)
                        }
                    }
                } label: {
                    Label("File Browser", systemImage: "folder")
                }

                DisclosureGroup {
                    cameraViewsContent
                } label: {
                    Label("Camera Views", systemImage: "camera.viewfinder")
                }

                DisclosureGroup {
                    exportContent
                } label: {
                    Label("Export", systemImage: "square.and.arrow.up")
                }

                DisclosureGroup {
                    materialsContent
                } label: {
                    Label("Materials", systemImage: "paintbrush")
                }

                DisclosureGroup {
                    LightingView()
                } label: {
                    Label("Lighting", systemImage: "lightbulb")
                }

                DisclosureGroup {
                    parametersContent
                } label: {
                    Label("Parameters", systemImage: "slider.horizontal.3")
                }

                DisclosureGroup {
                    manageModelsContent
                } label: {
                    Label("Manage Models", systemImage: "cube.transparent")
                }
            }
            .padding()
        }
    }

    // MARK: - Управление моделями

    private var manageModelsContent: some View {
        VStack(spacing: 10) {
            if appState.loadedModels.isEmpty {
                Text("No models loaded")
                    .foregroundColor(.secondary)
                    .padding()
            } else {
                Picker("Select Model", selection: $appState.selectedModelID) {
                    ForEach(appState.loadedModels) { model in
                        HStack {
                            Text(model.name)
                            if !model.isVisible {
                                Image(systemName: "eye.slash")
                            }
                        }
                        .tag(model.id as UUID?)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: .infinity)

                if let selectedModel = appState.loadedModels.first(where: {
                    $0.id == appState.selectedModelID
                }) {
                    Divider()
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Model Info:").font(.caption.bold())
                        Text(
                            "📏 Size: \(String(format: "%.1f", selectedModel.modelSize.x)) x \(String(format: "%.1f", selectedModel.modelSize.z)) x \(String(format: "%.1f", selectedModel.modelSize.y)) mm"
                        )
                        .font(.caption)
                        Text(
                            "📊 Reduction: \(String(format: "%.1f", selectedModel.optimizationReductionPercent))%"
                        )
                        .font(.caption)
                    }
                    Divider()
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Position (mm):").font(.caption.bold())
                        HStack {
                            Text("X:").frame(width: 25, alignment: .leading)
                            TextField(
                                "0",
                                value: $appState.newModelPositionX,
                                format: .number
                            )
                            .textFieldStyle(.roundedBorder).frame(width: 60)
                            Text("Y:").frame(width: 25, alignment: .leading)
                            TextField(
                                "0",
                                value: $appState.newModelPositionY,
                                format: .number
                            )
                            .textFieldStyle(.roundedBorder).frame(width: 60)
                            Text("Z:").frame(width: 25, alignment: .leading)
                            TextField(
                                "0",
                                value: $appState.newModelPositionZ,
                                format: .number
                            )
                            .textFieldStyle(.roundedBorder).frame(width: 60)
                        }
                        HStack {
                            Button("Update Position") {
                                appState.updateModelPosition(
                                    modelID: selectedModel.id,
                                    x: appState.newModelPositionX,
                                    y: appState.newModelPositionY,
                                    z: appState.newModelPositionZ
                                )
                            }
                            .buttonStyle(.borderedProminent).controlSize(.small)
                            Button("Reset to 0") {
                                appState.newModelPositionX = 0
                                appState.newModelPositionY = 0
                                appState.newModelPositionZ = 0
                                appState.updateModelPosition(
                                    modelID: selectedModel.id,
                                    x: 0,
                                    y: 0,
                                    z: 0
                                )
                            }
                            .buttonStyle(.bordered).controlSize(.small)
                        }
                    }
                    Divider()
                    HStack {
                        Button(action: {
                            appState.toggleModelVisibility(
                                modelID: selectedModel.id
                            )
                        }) {
                            Label(
                                selectedModel.isVisible ? "Hide" : "Show",
                                systemImage: selectedModel.isVisible
                                    ? "eye" : "eye.slash"
                            )
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                        Spacer()
                        Button(action: {
                            appState.removeModel(withID: selectedModel.id)
                        }) {
                            Label("Remove", systemImage: "trash")
                                .foregroundColor(.red)
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                    }
                }
            }
        }
        .padding(.vertical, 5)
    }

    // MARK: - Центральная панель

    private var centerPanel: some View {
        GCodeSceneView()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Правая панель

    private var rightPanel: some View {
        TabView {
            analyticsTab
                .tabItem { Label("Analytics", systemImage: "chart.bar") }
            logTab
                .tabItem { Label("Log", systemImage: "terminal") }
        }
    }

    private var analyticsTab: some View {
        VStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if let stats = appState.stats {
                        analyticsContent(stats: stats)
                    } else {
                        Text("No data.")
                    }
                }
                .padding()
            }
            Button("Copy Analytics") {
                copyAnalyticsToClipboard()
            }
            .buttonStyle(.bordered)
            .padding(.bottom, 8)
        }
    }

    private func analyticsContent(stats: GCodeStats) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("=== АНАЛИЗ GCODE ФАЙЛА ===").font(.headline)
            Text("\(stats.fileName), \(formatBytes(stats.fileSize))")
                .font(.caption).foregroundColor(.secondary)
            Divider()
            Text("1. Размеры модели:").fontWeight(.semibold)
            Text("- Высота (Z): \(String(format: "%.2f", stats.height)) мм")
            Text("- Длина (Y): \(String(format: "%.2f", stats.length)) мм")
            Text("- Ширина (X): \(String(format: "%.2f", stats.width)) мм")
            Text("2. Количество точек с экструзией: \(stats.extrusionPoints)")
                .fontWeight(.semibold)
            Text(
                "3. Длина пути печати: \(stats.extrusionPathLength.formattedWithSpaces) мм"
            )
            Text(
                "4. Скорость печати: \(String(format: "%.1f", stats.maxSpeedMmPerMin / 60.0)) мм/с"
            )
            Text(
                "5. Расчетное время печати: \(String(format: "%.1f", stats.estimatedPrintTimeMin/60)) ч."
            )
            Text("6. Количество слоев: \(stats.numLayers)")
            Divider()
            Text("7. Количество экструзии (код E):").fontWeight(.semibold)
            Text("- Всего: \(stats.totalExtrusion.formattedWithSpaces) мм")
            Text(
                "- На точку: мин \(String(format: "%.4f", stats.minEPerPoint)) мм (\(stats.minEPointCoords))"
            )
            Text(
                "- На точку: макс \(String(format: "%.4f", stats.maxEPerPoint)) мм (\(stats.maxEPointCoords))"
            )
            Divider()
            Text("=== OPTIMIZATION ===").font(.headline)
            Text("Original ext pts: \(stats.originalExtrusionPoints)")
            Text("Optimized ext pts: \(stats.optimizedExtrusionPoints)")
            Text(
                "Reduction: \(String(format: "%.1f", stats.optimizationReductionPercent))%"
            )
        }
        .padding(.horizontal, 4)
    }

    private var logTab: some View {
        VStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(appState.logMessages, id: \.self) { msg in
                        Text(msg).font(.system(.caption, design: .monospaced))
                    }
                }
                .padding()
            }
            Button("Copy Logs") {
                copyLogsToClipboard()
            }
            .buttonStyle(.bordered)
            .padding(.bottom, 8)
        }
    }

    // MARK: - Копирование в буфер

    private func copyAnalyticsToClipboard() {
        guard let stats = appState.stats else { return }
        let text = """
            === АНАЛИЗ GCODE ФАЙЛА ===
            \(stats.fileName), \(formatBytes(stats.fileSize))

            1. Размеры модели:
            - Высота (Z): \(String(format: "%.2f", stats.height)) мм
            - Длина (Y): \(String(format: "%.2f", stats.length)) мм
            - Ширина (X): \(String(format: "%.2f", stats.width)) мм

            2. Количество точек с экструзией: \(stats.extrusionPoints)
            3. Длина пути печати: \(stats.extrusionPathLength.formattedWithSpaces) мм
            4. Скорость печати: \(String(format: "%.1f", stats.maxSpeedMmPerMin / 60.0)) мм/с
            5. Расчетное время печати: \(String(format: "%.1f", stats.estimatedPrintTimeMin/60)) ч.
            6. Количество слоев: \(stats.numLayers)

            7. Количество экструзии (код E):
            - Всего: \(stats.totalExtrusion.formattedWithSpaces) мм
            - На точку: мин \(String(format: "%.4f", stats.minEPerPoint)) мм (\(stats.minEPointCoords))
            - На точку: макс \(String(format: "%.4f", stats.maxEPerPoint)) мм (\(stats.maxEPointCoords))

            === OPTIMIZATION ===
            Original ext pts: \(stats.originalExtrusionPoints)
            Optimized ext pts: \(stats.optimizedExtrusionPoints)
            Reduction: \(String(format: "%.1f", stats.optimizationReductionPercent))%
            """
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        appState.log("Analytics copied to clipboard")
    }

    private func copyLogsToClipboard() {
        let text = appState.logMessages.joined(separator: "\n")
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        appState.log("Logs copied to clipboard")
    }

    // MARK: - Вспомогательные компоненты

    private func formatBytes(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }

    private func sortButton(title: String, order: SortOrder) -> some View {
        Button(action: { appState.sortOrder = order }) {
            Text(title).font(.caption)
                .fontWeight(appState.sortOrder == order ? .bold : .regular)
                .foregroundColor(
                    appState.sortOrder == order ? .blue : .secondary
                )
        }
        .buttonStyle(.plain)
    }

    private var cameraViewsContent: some View {
        VStack(spacing: 10) {
            LazyVGrid(
                columns: [GridItem(.flexible()), GridItem(.flexible())],
                spacing: 5
            ) {
                CamButton(title: "Top", action: .top)
                CamButton(title: "Bottom", action: .bottom)
                CamButton(title: "Front", action: .front)
                CamButton(title: "Back", action: .back)
                CamButton(title: "Left", action: .left)
                CamButton(title: "Right", action: .right)
                CamButton(title: "ISO 1", action: .iso1)
                CamButton(title: "ISO 2", action: .iso2)
                CamButton(title: "ISO 3", action: .iso3)
                CamButton(title: "ISO 4", action: .iso4)
            }
            Button("Rotate 360°") { appState.cameraAction = .rotate360 }
                .buttonStyle(.bordered).frame(maxWidth: .infinity)
        }
    }

    private var exportContent: some View {
        VStack(spacing: 10) {
            Button(action: { appState.calculateAnalytics() }) {
                HStack {
                    Image(systemName: "chart.bar")
                    Text(
                        appState.isCalculatingAnalytics
                            ? "Calculating..." : "Calculate Analytics"
                    )
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(
                appState.rawPoints.isEmpty || appState.isCalculatingAnalytics
            )

            Divider()

            HStack {
                Text("Video W:")
                TextField("Width", value: $appState.videoWidth, format: .number)
                    .textFieldStyle(.roundedBorder).frame(width: 70)
                Text("H:")
                TextField(
                    "Height",
                    value: $appState.videoHeight,
                    format: .number
                )
                .textFieldStyle(.roundedBorder).frame(width: 70)
            }

            Button(action: { recordVideo() }) {
                HStack {
                    Image(
                        systemName: appState.isRecording
                            ? "stop.circle" : "video"
                    )
                    Text(
                        appState.isRecording
                            ? "Recording..." : "Record 360° Frames (JPEG)"
                    )
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
        LazyVGrid(
            columns: [GridItem(.flexible()), GridItem(.flexible())],
            spacing: 5
        ) {
            ForEach(MaterialPreset.allCases, id: \.self) { mat in
                if appState.selectedMaterial == mat {
                    Button(mat.rawValue) { appState.changeMaterial(mat) }
                        .buttonStyle(.borderedProminent)
                } else {
                    Button(mat.rawValue) { appState.changeMaterial(mat) }
                        .buttonStyle(.bordered)
                }
            }
        }
    }

    private var parametersContent: some View {
        VStack {
            Text("Tube Diameter (mm)")
            HStack {
                Slider(
                    value: $appState.tempTubeDiameter,
                    in: 1.0...10.0,
                    step: 0.5
                )
                Text(String(format: "%.1f", appState.tempTubeDiameter)).frame(
                    width: 35
                )
            }
            Button("Apply Diameter") { appState.applyDiameter() }
                .disabled(appState.rawPoints.isEmpty)

            Divider().padding(.vertical, 5)

            ColorPicker("Pick Color", selection: $appState.tempModelColor)
            Button("Apply Color") { appState.applyColor() }
                .disabled(appState.rawPoints.isEmpty)

            Divider().padding(.vertical, 5)

            Text("Collinear Angle Threshold (°)")
            HStack {
                Slider(
                    value: $appState.tempCollinearAngle,
                    in: 0.0...30.0,
                    step: 0.5
                )
                Text(String(format: "%.1f°", appState.tempCollinearAngle))
                    .frame(width: 40)
            }
            Text("Lower = more detail, Higher = faster")
                .font(.caption).foregroundColor(.secondary)
            Button("Apply Collinear Angle") { appState.applyCollinearAngle() }
                .disabled(appState.rawPoints.isEmpty)
        }
    }

    // MARK: - Логика (запись видео, фото и т.д.)

    private func selectDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            appState.currentDirectory = url
            appState.log("Selected directory: \(url.path)")
            appState.loadFilesFromDirectory(url)
        }
    }
    

    // MARK: - Video Recording (Retina + MSAA + высокое качество)

    private func recordVideo() {
        // 1. Диалог сохранения файла
        let savePanel = NSSavePanel()
        savePanel.allowedContentTypes = [.quickTimeMovie]
        savePanel.nameFieldStringValue = "model_rotation.mov"
        guard savePanel.runModal() == .OK, let outputURL = savePanel.url else {
            appState.log("Video save cancelled")
            return
        }

        let accessed = outputURL.startAccessingSecurityScopedResource()
        
        // 2. Получаем SCNView и узлы модели
        guard let sceneView = appState.sceneView ?? getSceneView(),
              let scene = sceneView.scene else {
            appState.log("SceneView not found")
            if accessed { outputURL.stopAccessingSecurityScopedResource() }
            return
        }

        let modelNodes = findAllGeometryNodes(in: scene.rootNode, excludingNames: ["axis", "grid"])
        guard !modelNodes.isEmpty else {
            appState.log("No model nodes to rotate")
            if accessed { outputURL.stopAccessingSecurityScopedResource() }
            return
        }
        let originalAngles = modelNodes.map { $0.eulerAngles.y }

        // 3. Параметры видео
        let scaleFactor = sceneView.window?.backingScaleFactor ?? NSScreen.main?.backingScaleFactor ?? 2.0
        let pixelWidth  = Int(sceneView.bounds.width * scaleFactor)
        let pixelHeight = Int(sceneView.bounds.height * scaleFactor)

        let width  = appState.videoWidth  > 0 ? Int(appState.videoWidth)  : pixelWidth
        let height = appState.videoHeight > 0 ? Int(appState.videoHeight) : pixelHeight
        appState.log("Video size: \(width)x\(height)")
        
        let totalFrames = 150
        let fps: Int32 = 30
        let sampleCount = 2
        let supersampling = 2

        // 4. Metal-устройство и рендерер
        guard let device = MTLCreateSystemDefaultDevice(),
              let commandQueue = device.makeCommandQueue() else {
            appState.log("Metal not available")
            if accessed { outputURL.stopAccessingSecurityScopedResource() }
            return
        }

        let renderer = SCNRenderer(device: device, options: nil)
        renderer.scene = scene
        renderer.pointOfView = sceneView.pointOfView
        renderer.autoenablesDefaultLighting = sceneView.autoenablesDefaultLighting

        // ВЫНОСИМ ВСЮ ТЯЖЕЛУЮ РАБОТУ В ФОНОВЫЙ ПОТОК
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            defer {
                if accessed { outputURL.stopAccessingSecurityScopedResource() }
                // Восстанавливаем исходный угол на главном потоке
                DispatchQueue.main.async {
                    for (idx, node) in modelNodes.enumerated() {
                        node.eulerAngles.y = originalAngles[idx]
                    }
                    SCNTransaction.flush()
                }
            }

            // Удаляем существующий файл
            if FileManager.default.fileExists(atPath: outputURL.path) {
                try? FileManager.default.removeItem(at: outputURL)
            }

            // 5. Настройка AVAssetWriter
            let writer: AVAssetWriter
            do {
                writer = try AVAssetWriter(outputURL: outputURL, fileType: .mov)
            } catch {
                DispatchQueue.main.async { appState.log("AVAssetWriter error: \(error)") }
                return
            }

            let compressionSettings: [String: Any] = [
                AVVideoQualityKey: 0.7,
                AVVideoMaxKeyFrameIntervalKey: fps * 1
            ]
            let videoSettings: [String: Any] = [
                AVVideoCodecKey: AVVideoCodecType.hevc,
                AVVideoWidthKey: width,
                AVVideoHeightKey: height,
                AVVideoCompressionPropertiesKey: compressionSettings
            ]
            let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
            writerInput.expectsMediaDataInRealTime = false // Мы подаем данные не в реальном времени

            // ВАЖНО: Указываем MetalCompatibility и IOSurfaceProperties для Zero-Copy рендеринга
            let sourcePixelBufferAttributes: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
                kCVPixelBufferMetalCompatibilityKey as String: true,
                kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]
            ]
            
            let adaptor = AVAssetWriterInputPixelBufferAdaptor(
                assetWriterInput: writerInput,
                sourcePixelBufferAttributes: sourcePixelBufferAttributes
            )

            guard writer.canAdd(writerInput) else {
                DispatchQueue.main.async { appState.log("Cannot add video input") }
                return
            }
            writer.add(writerInput)

            guard writer.startWriting() else {
                DispatchQueue.main.async { appState.log("Writer startWriting failed: \(writer.error?.localizedDescription ?? "")") }
                return
            }
            writer.startSession(atSourceTime: .zero)

            // 6. ПРЕДВАРИТЕЛЬНОЕ СОЗДАНИЕ РЕСУРСОВ METAL (Переиспользование)
            let renderWidth = width * supersampling
            let renderHeight = height * supersampling
            let pixelFormat: MTLPixelFormat = .bgra8Unorm_srgb

            // Текстура для Resolve из MSAA или для промежуточного суперсэмплинга
            var renderTexture: MTLTexture?
            if supersampling > 1 {
                let renderDesc = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: pixelFormat, width: renderWidth, height: renderHeight, mipmapped: false)
                renderDesc.usage = [.renderTarget, .shaderRead]
                renderDesc.storageMode = .private // Приватная, так как живет на GPU
                renderTexture = device.makeTexture(descriptor: renderDesc)
            }
            
            // MSAA текстура
            var msaaTexture: MTLTexture?
            if sampleCount > 1 {
                let msaaDesc = MTLTextureDescriptor()
                msaaDesc.textureType = .type2DMultisample
                msaaDesc.pixelFormat = pixelFormat
                msaaDesc.width = renderWidth
                msaaDesc.height = renderHeight
                msaaDesc.sampleCount = sampleCount
                msaaDesc.usage = .renderTarget
                msaaDesc.storageMode = .private
                msaaTexture = device.makeTexture(descriptor: msaaDesc)
            }
            
            let scaleFilter = supersampling > 1 ? MPSImageBilinearScale(device: device) : nil

            let frameDuration = CMTime(value: 1, timescale: fps)

            // 7. ПОТОКОВЫЙ РЕНДЕРИНГ (Без массива кадров)
            for i in 0..<totalFrames {
                let progress = Double(i) / Double(totalFrames)
                let angle = CGFloat(progress * 2.0 * .pi)

                // Поворачиваем модель (безопасно делать на фоне, если нет параллельного рендера вьюшки, но лучше через sync на main)
                DispatchQueue.main.sync {
                    for (idx, node) in modelNodes.enumerated() {
                        node.eulerAngles.y = originalAngles[idx] + angle
                    }
                    SCNTransaction.flush()
                }

                // Берем CVPixelBuffer из пула адаптера (ОЧЕНЬ БЫСТРО)
                var pixelBuffer: CVPixelBuffer?
                CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, adaptor.pixelBufferPool!, &pixelBuffer)
                guard let buffer = pixelBuffer else {
                    appState.log("Failed to get buffer from pool at frame \(i)")
                    break
                }

                // Достаем IOSurface из буфера для прямого рендера в него (ZERO-COPY)
                guard let surface = CVPixelBufferGetIOSurface(buffer)?.takeUnretainedValue() else {
                    appState.log("Failed to get IOSurface at frame \(i)")
                    break
                }

                let outDesc = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: pixelFormat, width: width, height: height, mipmapped: false)
                outDesc.usage = [.shaderWrite, .shaderRead, .renderTarget]
                // Создаем текстуру-обертку над IOSurface (без аллокации новой памяти)
                guard let outputTexture = device.makeTexture(descriptor: outDesc, iosurface: surface, plane: 0) else {
                    appState.log("Failed to create output texture from IOSurface at frame \(i)")
                    break
                }

                // --- РЕНДЕР СЦЕНЫ ---
                let passDesc = MTLRenderPassDescriptor()
                passDesc.colorAttachments[0].loadAction = .clear
                passDesc.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)

                // Логика маршрутизации текстур (MSAA + Supersampling)
                if let msaaTex = msaaTexture {
                    passDesc.colorAttachments[0].texture = msaaTex
                    passDesc.colorAttachments[0].storeAction = .multisampleResolve
                    // Если есть суперсэмплинг, резолвим в промежуточную текстуру, иначе сразу в IOSurface
                    passDesc.colorAttachments[0].resolveTexture = renderTexture ?? outputTexture
                } else {
                    passDesc.colorAttachments[0].texture = renderTexture ?? outputTexture
                    passDesc.colorAttachments[0].storeAction = .store
                }

                guard let renderCmdBuf = commandQueue.makeCommandBuffer() else { break }
                renderer.render(atTime: 0,
                                viewport: CGRect(x: 0, y: 0, width: CGFloat(renderWidth), height: CGFloat(renderHeight)),
                                commandBuffer: renderCmdBuf,
                                passDescriptor: passDesc)
                renderCmdBuf.commit()
                renderCmdBuf.waitUntilCompleted() // Ждем завершения GPU

                // --- МАСШТАБИРОВАНИЕ (ЕСЛИ НУЖНО) ---
                if let scale = scaleFilter, let rTex = renderTexture {
                    guard let scaleCmdBuf = commandQueue.makeCommandBuffer() else { break }
                    scale.encode(commandBuffer: scaleCmdBuf, sourceTexture: rTex, destinationTexture: outputTexture)
                    scaleCmdBuf.commit()
                    scaleCmdBuf.waitUntilCompleted()
                }

                // --- ЗАПИСЬ КАДРА В ВИДЕО ---
                while !writerInput.isReadyForMoreMediaData {
                    Thread.sleep(forTimeInterval: 0.01)
                }
                
                let time = CMTimeMultiply(frameDuration, multiplier: Int32(i))
                if !adaptor.append(buffer, withPresentationTime: time) {
                    appState.log("Failed to append frame \(i)")
                    break
                }
            }

            // 8. Завершение записи
            writerInput.markAsFinished()
            writer.finishWriting {
                DispatchQueue.main.async {
                    if writer.status == .completed {
                        self.appState.log("Video saved: \(outputURL.path)")
                    } else {
                        self.appState.log("Video writing failed: \(writer.error?.localizedDescription ?? "unknown")")
                    }
                }
            }
        }
    }

    /// Оптимизированный поиск узлов
    private func findAllGeometryNodes(in node: SCNNode, excludingNames: Set<String>) -> [SCNNode] {
        var result: [SCNNode] = []
        if node.geometry != nil, node.name.map { !excludingNames.contains($0) } ?? true {
            result.append(node)
        }
        for child in node.childNodes {
            result.append(contentsOf: findAllGeometryNodes(in: child, excludingNames: excludingNames))
        }
        return result
    }
    
    
    // MARK: - Video Recording

    private func recordVideo0() {
        return
    }

        
    private func savePhotos() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.prompt = "Choose folder to save photos"

        if panel.runModal() == .OK, let dir = panel.url {
            guard let sceneView = getSceneView() else { return }

            let views: [(String, CameraAction)] = [
                ("Front", .front), ("Back", .back), ("Left", .left),
                ("Right", .right),
                ("Top", .top), ("Bottom", .bottom),
                ("ISO_1", .iso1), ("ISO_2", .iso2), ("ISO_3", .iso3),
                ("ISO_4", .iso4),
            ]

            appState.log("Saving photos to \(dir.path)...")

            for (name, action) in views {
                appState.cameraAction = action
                RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))

                if let imgRep = sceneView.snapshot().tiffRepresentation,
                    let img = NSImage(data: imgRep)
                {
                    let fileURL = dir.appendingPathComponent("\(name).png")
                    if let tiffData = img.tiffRepresentation,
                        let bitmap = NSBitmapImageRep(data: tiffData),
                        let pngData = bitmap.representation(
                            using: .png,
                            properties: [:]
                        )
                    {
                        try? pngData.write(to: fileURL)
                    }
                }
            }
            appState.log("Photos saved successfully!")
        }
    }

    private func getSceneView() -> SCNView? {
        NSApp.windows.first?.contentViewController?.view.subviews.first(where: {
            $0 is SCNView
        }) as? SCNView
    }
}

struct CamButton: View {
    var title: String
    var action: CameraAction
    @EnvironmentObject var appState: AppState
    var body: some View {
        Button(title) { appState.cameraAction = action }
            .buttonStyle(.bordered)
    }
}

extension Float {
    var formattedWithSpaces: String {
        String(format: "%.2f", locale: Locale(identifier: "en_US"), self)
            .replacingOccurrences(of: ",", with: " ")
    }
}
