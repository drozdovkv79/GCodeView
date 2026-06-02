import SwiftUI
import UniformTypeIdentifiers
import SceneKit
import AVFoundation

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    // Sheet / overlay states
    @State private var showLeftPanel = false
    @State private var showRightPanel = false
    @State private var showCameraMenu = false
    @State private var showFilePicker = false
    @State private var activeSheet: ActiveSheet?

    enum ActiveSheet: Identifiable {
        case left, right, cameraViews
        var id: Int { hashValue }
    }

    var body: some View {
        NavigationView {
            ZStack {
                // 3D Scene - full screen
                GCodeSceneView()
                    .ignoresSafeArea()

                // Loading overlay
                if appState.isLoading {
                    VStack(spacing: 12) {
                        ProgressView()
                            .scaleEffect(1.5)
                            .tint(.white)
                        Text("Loading…")
                            .foregroundColor(.white)
                        ProgressView(value: appState.progress, total: 100)
                            .frame(width: 200)
                            .tint(.blue)
                        Text(String(format: "%.0f%%", appState.progress))
                            .foregroundColor(.white)
                            .font(.caption)
                    }
                    .padding(20)
                    .background(Color.black.opacity(0.7))
                    .cornerRadius(16)
                }

                // Floating buttons
                VStack {
                    Spacer()
                    HStack {
                        // Left panel toggle
                        Button { activeSheet = .left } label: {
                            Image(systemName: "sidebar.left")
                                .floatingButton()
                        }

                        Spacer()

                        // Camera views
                        Button { activeSheet = .cameraViews } label: {
                            Image(systemName: "camera.viewfinder")
                                .floatingButton()
                        }

                        // Show/hide axis
                        Button { appState.showAxis.toggle() } label: {
                            Image(systemName: appState.showAxis ? "move.3d" : "square.dashed")
                                .floatingButton()
                        }

                        // Right panel (analytics/log)
                        Button { activeSheet = .right } label: {
                            Image(systemName: "chart.bar")
                                .floatingButton()
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 30)
                }
            }
            .navigationTitle("GCode Viewer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button { activeSheet = .left } label: {
                        Image(systemName: "folder")
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { activeSheet = .right } label: {
                        Image(systemName: "info.circle")
                    }
                }
            }
            .sheet(item: $activeSheet) { sheet in
                switch sheet {
                case .left:    LeftPanelSheet()
                case .right:   RightPanelSheet()
                case .cameraViews: CameraViewsSheet()
                }
            }
        }
        .navigationViewStyle(.stack)
        .onAppear {
            if appState.tempTubeDiameter == 0 { appState.tempTubeDiameter = 6.0 }
        }
    }
}

// MARK: - Floating button style helper

private extension Image {
    func floatingButton() -> some View {
        self.font(.system(size: 20))
            .foregroundColor(.white)
            .frame(width: 44, height: 44)
            .background(Color.black.opacity(0.55))
            .clipShape(Circle())
    }
}

// MARK: - Left Panel Sheet

struct LeftPanelSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss
    @State private var showFilePicker = false
    @State private var expandFiles = true
    @State private var expandParams = true
    @State private var expandModels = false
    @State private var expandMaterials = false
    @State private var expandLighting = false
    @State private var expandExport = false

    var body: some View {
        NavigationView {
            List {
                // ── File Browser ────────────────────────────────────────
                Section {
                    if expandFiles {
                        fileBrowserContent
                    }
                } header: {
                    sectionHeader("File Browser", systemImage: "folder", expanded: $expandFiles)
                }

                // ── Parameters ──────────────────────────────────────────
                Section {
                    if expandParams {
                        parametersContent
                    }
                } header: {
                    sectionHeader("Parameters", systemImage: "slider.horizontal.3", expanded: $expandParams)
                }

                // ── Materials ───────────────────────────────────────────
                Section {
                    if expandMaterials {
                        materialsContent
                    }
                } header: {
                    sectionHeader("Materials", systemImage: "paintbrush", expanded: $expandMaterials)
                }

                // ── Lighting ────────────────────────────────────────────
                Section {
                    if expandLighting {
                        LightingView()
                            .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 12))
                    }
                } header: {
                    sectionHeader("Lighting", systemImage: "lightbulb", expanded: $expandLighting)
                }

                // ── Manage Models ───────────────────────────────────────
                Section {
                    if expandModels {
                        manageModelsContent
                    }
                } header: {
                    sectionHeader("Manage Models", systemImage: "cube.transparent", expanded: $expandModels)
                }

                // ── Export ──────────────────────────────────────────────
                Section {
                    if expandExport {
                        exportContent
                    }
                } header: {
                    sectionHeader("Export / Analytics", systemImage: "square.and.arrow.up", expanded: $expandExport)
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showFilePicker) {
                DocumentPicker(types: [
                    UTType(filenameExtension: "gcode")!,
                    UTType(filenameExtension: "nc")!,
                    UTType(filenameExtension: "ngc") ?? .plainText
                ]) { url in
                    appState.selectedFileURL = url
                    appState.loadSelectedFile()
                    appState.shouldResetCamera = true
                }
            }
        }
    }

    // MARK: Section header helper
    private func sectionHeader(_ title: String, systemImage: String, expanded: Binding<Bool>) -> some View {
        Button {
            withAnimation { expanded.wrappedValue.toggle() }
        } label: {
            HStack {
                Label(title, systemImage: systemImage)
                Spacer()
                Image(systemName: expanded.wrappedValue ? "chevron.up" : "chevron.down")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .foregroundColor(.primary)
    }

    // MARK: File browser
    private var fileBrowserContent: some View {
        VStack(spacing: 10) {
            Button {
                showFilePicker = true
            } label: {
                Label("Open GCode File…", systemImage: "doc.badge.plus")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)

            if let url = appState.selectedFileURL {
                HStack {
                    Image(systemName: "doc.text").foregroundColor(.secondary)
                    Text(url.lastPathComponent).lineLimit(1).truncationMode(.middle)
                }
                .font(.caption)
                .padding(8)
                .background(Color(.secondarySystemGroupedBackground))
                .cornerRadius(8)
            }

            if appState.isLoading {
                ProgressView(value: appState.progress, total: 100)
                    .padding(.vertical, 4)
            }

            if !appState.fileItems.isEmpty {
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        sortButton(title: "Name", order: .name)
                        sortButton(title: "Size", order: .size)
                        sortButton(title: "Date", order: .date)
                    }
                    .padding(4)
                    .background(Color(.tertiarySystemGroupedBackground))
                    .cornerRadius(8)

                    ForEach(appState.sortedFiles) { item in
                        Button {
                            appState.selectedFileURL = item.url
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.name).lineLimit(1).font(.subheadline)
                                        .foregroundColor(appState.selectedFileURL == item.url ? .blue : .primary)
                                    Text("\(item.formattedSize) · \(item.formattedDate)")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                                Spacer()
                                if appState.selectedFileURL == item.url {
                                    Image(systemName: "checkmark").foregroundColor(.blue)
                                }
                            }
                            .padding(.vertical, 6)
                        }
                        .buttonStyle(.plain)
                        Divider()
                    }
                }
                .background(Color(.secondarySystemGroupedBackground))
                .cornerRadius(8)
            }

            HStack(spacing: 8) {
                Button {
                    appState.loadSelectedFile()
                    appState.shouldResetCamera = true
                } label: {
                    Text(appState.isLoading ? "Loading…" : "Load (Replace)")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(appState.selectedFileURL == nil || appState.isLoading)

                Button {
                    appState.addModel()
                } label: {
                    Text("Add")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(appState.selectedFileURL == nil || appState.isLoading)
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: Parameters
    private var parametersContent: some View {
        VStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("Tube Diameter (mm)").font(.subheadline)
                    Spacer()
                    Text(String(format: "%.1f", appState.tempTubeDiameter)).foregroundColor(.secondary)
                }
                Slider(value: $appState.tempTubeDiameter, in: 1.0...10.0, step: 0.5)
                Button("Apply Diameter") { appState.applyDiameter() }
                    .buttonStyle(.bordered).controlSize(.small)
                    .disabled(appState.rawPoints.isEmpty)
            }

            Divider()

            VStack(alignment: .leading, spacing: 4) {
                ColorPicker("Model Color", selection: $appState.tempModelColor)
                Button("Apply Color") { appState.applyColor() }
                    .buttonStyle(.bordered).controlSize(.small)
                    .disabled(appState.rawPoints.isEmpty)
            }

            Divider()

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("Collinear Angle (°)").font(.subheadline)
                    Spacer()
                    Text(String(format: "%.1f°", appState.tempCollinearAngle)).foregroundColor(.secondary)
                }
                Slider(value: $appState.tempCollinearAngle, in: 0.0...30.0, step: 0.5)
                Text("Lower = more detail, Higher = faster")
                    .font(.caption2).foregroundColor(.secondary)
                Button("Apply Collinear Angle") { appState.applyCollinearAngle() }
                    .buttonStyle(.bordered).controlSize(.small)
                    .disabled(appState.rawPoints.isEmpty)
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: Materials
    private var materialsContent: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
            ForEach(MaterialPreset.allCases, id: \.self) { mat in
                Button(mat.rawValue) { appState.changeMaterial(mat) }
                    .buttonStyle(PlainButtonStyle())
                    .padding(6)
                    .frame(maxWidth: .infinity)
                    .background(Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(6)
            }
        }
        .padding(.vertical, 6)
    }

    
    
    // MARK: Manage Models
    private var manageModelsContent: some View {
        VStack(spacing: 10) {
            if appState.loadedModels.isEmpty {
                Text("No models loaded").foregroundColor(.secondary)
            } else {
                Picker("Model", selection: $appState.selectedModelID) {
                    ForEach(appState.loadedModels) { model in
                        Text(model.name).tag(model.id as UUID?)
                    }
                }
                .pickerStyle(.menu)

                if let model = appState.loadedModels.first(where: { $0.id == appState.selectedModelID }) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("📏 \(String(format: "%.1f", model.modelSize.x)) × \(String(format: "%.1f", model.modelSize.z)) × \(String(format: "%.1f", model.modelSize.y)) mm")
                            .font(.caption)
                        Text("📊 Reduction: \(String(format: "%.1f", model.optimizationReductionPercent))%")
                            .font(.caption)
                    }
                    .padding(8)
                    .background(Color(.tertiarySystemGroupedBackground))
                    .cornerRadius(8)

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Position (mm):").font(.caption.bold())
                        HStack(spacing: 8) {
                            labeledField("X", value: $appState.newModelPositionX)
                            labeledField("Y", value: $appState.newModelPositionY)
                            labeledField("Z", value: $appState.newModelPositionZ)
                        }
                        HStack(spacing: 8) {
                            Button("Update Pos") {
                                appState.updateModelPosition(modelID: model.id,
                                    x: appState.newModelPositionX,
                                    y: appState.newModelPositionY,
                                    z: appState.newModelPositionZ)
                            }
                            .buttonStyle(.borderedProminent).controlSize(.small)
                            Button("Reset") {
                                appState.newModelPositionX = 0; appState.newModelPositionY = 0; appState.newModelPositionZ = 0
                                appState.updateModelPosition(modelID: model.id, x: 0, y: 0, z: 0)
                            }
                            .buttonStyle(.bordered).controlSize(.small)
                        }
                    }

                    HStack {
                        Button {
                            appState.toggleModelVisibility(modelID: model.id)
                        } label: {
                            Label(model.isVisible ? "Hide" : "Show",
                                  systemImage: model.isVisible ? "eye" : "eye.slash")
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                        Spacer()
                        Button(role: .destructive) {
                            appState.removeModel(withID: model.id)
                        } label: {
                            Label("Remove", systemImage: "trash")
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                    }
                }
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: Export
    private var exportContent: some View {
        VStack(spacing: 10) {
            Button {
                appState.calculateAnalytics()
            } label: {
                Label(appState.isCalculatingAnalytics ? "Calculating…" : "Calculate Analytics",
                      systemImage: "chart.bar")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(appState.rawPoints.isEmpty || appState.isCalculatingAnalytics)

            Divider()

            Text("Video export is available in the Analytics tab.")
                .font(.caption).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.vertical, 6)
    }

    // MARK: Helpers
    private func sortButton(title: String, order: SortOrder) -> some View {
        Button(title) { appState.sortOrder = order }
            .font(.caption)
            .fontWeight(appState.sortOrder == order ? .bold : .regular)
            .foregroundColor(appState.sortOrder == order ? .blue : .secondary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 4)
            .buttonStyle(.plain)
    }

    private func labeledField(_ label: String, value: Binding<Float>) -> some View {
        HStack(spacing: 2) {
            Text(label).font(.caption).frame(width: 14)
            TextField("0", value: value, format: .number)
                .keyboardType(.decimalPad)
                .textFieldStyle(.roundedBorder)
                .frame(width: 55)
                .font(.caption)
        }
    }
}

// MARK: - Camera Views Sheet

struct CameraViewsSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    let views: [(String, CameraAction)] = [
        ("Top", .top), ("Bottom", .bottom),
        ("Front", .front), ("Back", .back),
        ("Left", .left), ("Right", .right),
        ("ISO 1", .iso1), ("ISO 2", .iso2),
        ("ISO 3", .iso3), ("ISO 4", .iso4)
    ]

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    ForEach(views, id: \.0) { title, action in
                        Button(title) {
                            appState.cameraAction = action
                            dismiss()
                        }
                        .buttonStyle(.bordered)
                        .frame(maxWidth: .infinity)
                    }
                }
                .padding()
                Button("Rotate 360°") {
                    appState.cameraAction = .rotate360
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .frame(maxWidth: .infinity)
                .padding(.horizontal)
            }
            .navigationTitle("Camera Views")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) { Button("Done") { dismiss() } }
            }
        }
        .presentationDetents([.medium])
    }
}

// MARK: - Right Panel Sheet (Analytics + Log)

struct RightPanelSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss
    @State private var selectedTab = 0

    var body: some View {
        NavigationView {
            TabView(selection: $selectedTab) {
                analyticsTab.tabItem { Label("Analytics", systemImage: "chart.bar") }.tag(0)
                logTab.tabItem { Label("Log", systemImage: "terminal") }.tag(1)
                videoTab.tabItem { Label("Video", systemImage: "video") }.tag(2)
            }
            .navigationTitle(selectedTab == 0 ? "Analytics" : selectedTab == 1 ? "Log" : "Export Video")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) { Button("Done") { dismiss() } }
            }
        }
    }

    private var analyticsTab: some View {
        VStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if let stats = appState.stats {
                        analyticsContent(stats: stats)
                    } else {
                        VStack(spacing: 12) {
                            Text("No data loaded yet.").foregroundColor(.secondary)
                            Button("Calculate Analytics") { appState.calculateAnalytics() }
                                .buttonStyle(.borderedProminent)
                                .disabled(appState.rawPoints.isEmpty)
                        }
                        .frame(maxWidth: .infinity).padding(.top, 40)
                    }
                }
                .padding()
            }
            Button("Copy Analytics") { copyAnalytics() }
                .buttonStyle(.bordered).padding(.bottom, 8)
        }
    }

    private func analyticsContent(stats: GCodeStats) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("=== АНАЛИЗ GCODE ФАЙЛА ===").font(.headline)
            Text("\(stats.fileName), \(ByteCountFormatter.string(fromByteCount: stats.fileSize, countStyle: .file))")
                .font(.caption).foregroundColor(.secondary)
            Divider()
            Group {
                Text("1. Размеры модели:").fontWeight(.semibold)
                Text("- Высота (Z): \(String(format: "%.2f", stats.height)) мм")
                Text("- Длина (Y): \(String(format: "%.2f", stats.length)) мм")
                Text("- Ширина (X): \(String(format: "%.2f", stats.width)) мм")
            }
            Group {
                Text("2. Точек с экструзией: \(stats.extrusionPoints)").fontWeight(.semibold)
                Text("3. Длина пути: \(stats.extrusionPathLength.formattedWithSpaces) мм")
                Text("4. Скорость: \(String(format: "%.1f", stats.maxSpeedMmPerMin / 60)) мм/с")
                Text("5. Время печати: \(String(format: "%.1f", stats.estimatedPrintTimeMin/60)) ч.")
                Text("6. Слоев: \(stats.numLayers)")
            }
            Divider()
            Group {
                Text("7. Экструзия (E):").fontWeight(.semibold)
                Text("- Всего: \(stats.totalExtrusion.formattedWithSpaces) мм")
                Text("- Мин: \(String(format: "%.4f", stats.minEPerPoint)) мм")
                Text("- Макс: \(String(format: "%.4f", stats.maxEPerPoint)) мм")
            }
            Divider()
            Group {
                Text("=== OPTIMIZATION ===").font(.headline)
                Text("Original pts: \(stats.originalExtrusionPoints)")
                Text("Optimized pts: \(stats.optimizedExtrusionPoints)")
                Text("Reduction: \(String(format: "%.1f", stats.optimizationReductionPercent))%")
            }
        }
        .font(.system(.caption, design: .monospaced))
    }

    private var logTab: some View {
        VStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(Array(appState.logMessages.enumerated()), id: \.offset) { idx, msg in
                            Text(msg)
                                .font(.system(.caption2, design: .monospaced))
                                .id(idx)
                        }
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: appState.logMessages.count) { _ in
                    if let last = appState.logMessages.indices.last {
                        proxy.scrollTo(last, anchor: .bottom)
                    }
                }
            }
            Button("Copy Logs") { copyLogs() }
                .buttonStyle(.bordered).padding(.bottom, 8)
        }
    }

    private var videoTab: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Video Resolution").font(.subheadline.bold())
                HStack {
                    Text("W:").frame(width: 20)
                    TextField("1920", value: $appState.videoWidth, format: .number)
                        .keyboardType(.numberPad)
                        .textFieldStyle(.roundedBorder).frame(width: 80)
                    Text("H:").frame(width: 20)
                    TextField("1080", value: $appState.videoHeight, format: .number)
                        .keyboardType(.numberPad)
                        .textFieldStyle(.roundedBorder).frame(width: 80)
                }
            }
            .padding()
            .background(Color(.secondarySystemGroupedBackground))
            .cornerRadius(12)

            Button {
                recordVideo()
            } label: {
                Label(appState.isRecording ? "Recording…" : "Record 360° Video (MP4)",
                      systemImage: appState.isRecording ? "stop.circle" : "video")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .foregroundColor(appState.isRecording ? .red : .primary)
            .disabled(appState.rawPoints.isEmpty || appState.isRecording)

            Button {
                savePhotos()
            } label: {
                Label("Save 10 View Photos", systemImage: "photo.on.rectangle")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(appState.rawPoints.isEmpty)

            Spacer()
        }
        .padding()
    }

    // MARK: Copy helpers

    private func copyAnalytics() {
        guard let stats = appState.stats else { return }
        let text = """
        === АНАЛИЗ GCODE ===
        \(stats.fileName)
        Высота: \(String(format: "%.2f", stats.height)) мм
        Длина: \(String(format: "%.2f", stats.length)) мм
        Ширина: \(String(format: "%.2f", stats.width)) мм
        Точек: \(stats.extrusionPoints)
        Слоев: \(stats.numLayers)
        Reduction: \(String(format: "%.1f", stats.optimizationReductionPercent))%
        """
        UIPasteboard.general.string = text
        appState.log("Analytics copied to clipboard")
    }

    private func copyLogs() {
        UIPasteboard.general.string = appState.logMessages.joined(separator: "\n")
        appState.log("Logs copied to clipboard")
    }

    // MARK: Video recording (iOS version — saves to photo library)

    private func recordVideo() {
        guard let sceneView = appState.sceneView else {
            appState.log("Error: no 3D view for recording.")
            return
        }

        let outputURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("GCode_Rotation_\(Int(Date().timeIntervalSince1970)).mp4")

        try? FileManager.default.removeItem(at: outputURL)

        appState.isRecording = true
        appState.log("Preparing video recording…")

        DispatchQueue.global(qos: .userInitiated).async {
            var width = max(2, appState.videoWidth); var height = max(2, appState.videoHeight)
            if width % 2 != 0 { width += 1 }; if height % 2 != 0 { height += 1 }

            let fps: Int32 = 30; let duration: Double = 3.0
            let totalFrames = Int(Double(fps) * duration)

            do {
                let videoWriter = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
                let outputSettings: [String: Any] = [
                    AVVideoCodecKey: AVVideoCodecType.h264,
                    AVVideoWidthKey: NSNumber(value: width),
                    AVVideoHeightKey: NSNumber(value: height)
                ]
                let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: outputSettings)
                writerInput.expectsMediaDataInRealTime = false
                let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: writerInput,
                    sourcePixelBufferAttributes: [
                        kCVPixelBufferPixelFormatTypeKey as String: NSNumber(value: kCVPixelFormatType_32ARGB),
                        kCVPixelBufferWidthKey as String: NSNumber(value: width),
                        kCVPixelBufferHeightKey as String: NSNumber(value: height)
                    ])
                videoWriter.add(writerInput)
                videoWriter.startWriting()
                guard videoWriter.status == .writing else {
                    DispatchQueue.main.async { appState.isRecording = false }; return
                }
                videoWriter.startSession(atSourceTime: .zero)
                guard let pixelBufferPool = adaptor.pixelBufferPool else {
                    DispatchQueue.main.async { appState.isRecording = false }; return
                }

                let ciContext = CIContext()
                let colorSpace = CGColorSpaceCreateDeviceRGB()
                let videoBounds = CGRect(x: 0, y: 0, width: width, height: height)
                var frameCount: Int64 = 0

                for i in 0..<totalFrames {
                    let angle = Float(Double(i) / Double(totalFrames) * 2 * .pi)
                    var snapshot: UIImage?
                    DispatchQueue.main.sync {
                        sceneView.scene?.rootNode.childNode(withName: "gcode_container", recursively: false)?.eulerAngles.y = Float(CGFloat(angle))
                        snapshot = sceneView.snapshot()
                    }
                    if let img = snapshot?.cgImage {
                        while !writerInput.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.01) }
                        var pixelBuffer: CVPixelBuffer?
                        CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pixelBufferPool, &pixelBuffer)
                        if let buffer = pixelBuffer {
                            var ciImage = CIImage(cgImage: img)
                            let sx = CGFloat(width) / ciImage.extent.width
                            let sy = CGFloat(height) / ciImage.extent.height
                            let scale = min(sx, sy)
                            ciImage = ciImage.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                            let ox = (CGFloat(width) - ciImage.extent.width) / 2
                            let oy = (CGFloat(height) - ciImage.extent.height) / 2
                            ciImage = ciImage.transformed(by: CGAffineTransform(translationX: ox, y: oy))
                            let bg = CIImage(color: .black).cropped(to: videoBounds)
                            CVPixelBufferLockBaseAddress(buffer, [])
                            ciContext.render(ciImage.composited(over: bg), to: buffer, bounds: videoBounds, colorSpace: colorSpace)
                            CVPixelBufferUnlockBaseAddress(buffer, [])
                            adaptor.append(buffer, withPresentationTime: CMTimeMake(value: frameCount, timescale: fps))
                        }
                    }
                    frameCount += 1
                }

                writerInput.markAsFinished()
                videoWriter.finishWriting {
                    DispatchQueue.main.async {
                        appState.isRecording = false
                        if videoWriter.status == .completed {
                            // Share via activity sheet
                            let av = UIActivityViewController(activityItems: [outputURL], applicationActivities: nil)
                            if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                               let vc = scene.windows.first?.rootViewController {
                                vc.present(av, animated: true)
                            }
                            appState.log("Video ready: \(outputURL.lastPathComponent)")
                        } else {
                            appState.log("Video error: \(videoWriter.error?.localizedDescription ?? "unknown")")
                        }
                    }
                }
            } catch {
                DispatchQueue.main.async {
                    appState.isRecording = false
                    appState.log("Video error: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: Save photos (iOS — share sheet)

    private func savePhotos() {
        guard let sceneView = appState.sceneView else { return }
        let views: [(String, CameraAction)] = [
            ("Front", .front), ("Back", .back), ("Left", .left), ("Right", .right),
            ("Top", .top), ("Bottom", .bottom),
            ("ISO_1", .iso1), ("ISO_2", .iso2), ("ISO_3", .iso3), ("ISO_4", .iso4)
        ]
        var images: [UIImage] = []
        for (_, action) in views {
            appState.cameraAction = action
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
            images.append(sceneView.snapshot())
        }
        let av = UIActivityViewController(activityItems: images, applicationActivities: nil)
        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let vc = scene.windows.first?.rootViewController {
            vc.present(av, animated: true)
        }
        appState.log("Photos shared.")
    }
}

// MARK: - DocumentPicker

struct DocumentPicker: UIViewControllerRepresentable {
    let types: [UTType]
    let onPick: (URL) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        init(onPick: @escaping (URL) -> Void) { self.onPick = onPick }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            if let url = urls.first { onPick(url) }
        }
    }
}

// MARK: - CamButton

struct CamButton: View {
    var title: String; var action: CameraAction
    @EnvironmentObject var appState: AppState
    var body: some View {
        Button(title) { appState.cameraAction = action }.buttonStyle(.bordered)
    }
}

// MARK: - Float extension

extension Float {
    var formattedWithSpaces: String {
        String(format: "%.2f", locale: Locale(identifier: "en_US"), self)
    }
}
