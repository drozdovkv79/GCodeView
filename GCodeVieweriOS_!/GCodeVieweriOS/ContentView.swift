import SwiftUI
import UniformTypeIdentifiers
import Photos

struct ContentView: View {
    @StateObject var appState = AppState()
    @State private var showFileImporter = false
    @State private var showSettings = false
    
    var body: some View {
        ZStack {
            TabView {
                // ВКЛАДКА 1: 3D Просмотр
                ZStack {
                    Color.black.ignoresSafeArea()
                    
                    if appState.rawPoints.isEmpty {
                        VStack(spacing: 20) {
                            Image(systemName: "cube.transparent")
                                .font(.system(size: 60))
                                .foregroundColor(.gray)
                            Text("Откройте GCode файл")
                                .font(.title2)
                                .foregroundColor(.gray)
                            Button("Выбрать файл") { showFileImporter = true }
                                .buttonStyle(.borderedProminent)
                        }
                    } else if appState.isLoading {
                        VStack {
                            ProgressView()
                            Text("Загрузка модели...")
                                .foregroundColor(.white)
                                .padding(.top)
                        }
                    } else {
                        IosGCodeSceneView()
                            .environmentObject(appState)
                            .ignoresSafeArea()
                    }
                    
                    if !appState.rawPoints.isEmpty && !appState.isLoading {
                        VStack {
                            HStack {
                                Spacer()
                                Button(action: {
                                    withAnimation(.spring()) { showSettings.toggle() }
                                }) {
                                    Image(systemName: "gearshape.fill")
                                        .font(.title2)
                                        .foregroundColor(.white)
                                        .padding(12)
                                        .background(Color.black.opacity(0.6))
                                        .clipShape(Circle())
                                }
                                .padding(.trailing, 16)
                                .padding(.top, 50)
                            }
                            Spacer()
                        }
                    }
                    
                    if appState.isRecording {
                        VStack {
                            HStack {
                                HStack(spacing: 8) {
                                    Circle().fill(Color.red).frame(width: 12, height: 12)
                                    Text("REC").foregroundColor(.white).font(.caption).fontWeight(.bold)
                                }
                                .padding(8).background(Color.black.opacity(0.7)).cornerRadius(8)
                                .padding(.leading, 16).padding(.top, 55)
                                Spacer()
                            }
                            Spacer()
                        }
                    }
                }
                .tabItem { Label("3D Вид", systemImage: "cube") }
                
                // ВКЛАДКА 2: Файлы и Аналитика
                NavigationView {
                    List {
                        Section(header: Text("Файл")) {
                            if let url = appState.selectedFileURL {
                                HStack {
                                    Image(systemName: "doc.text.fill")
                                    Text(url.lastPathComponent).lineLimit(1)
                                    Spacer()
                                }
                            } else {
                                Text("Файл не выбран").foregroundColor(.secondary)
                            }
                            Button(action: { showFileImporter = true }) {
                                Label("Открыть файл .gcode", systemImage: "folder")
                            }
                        }
                        
                        Section(header: Text("Аналитика")) {
                            Button(action: { appState.calculateAnalytics() }) {
                                if appState.isCalculatingAnalytics { ProgressView() } else { Label("Рассчитать", systemImage: "chart.bar.fill") }
                            }
                            .disabled(appState.rawPoints.isEmpty || appState.isCalculatingAnalytics)
                            
                            if let stats = appState.stats {
                                Group {
                                    HStack { Text("Ширина (X)"); Spacer(); Text("\(String(format: "%.1f", stats.width)) мм") }
                                    HStack { Text("Длина (Y)"); Spacer(); Text("\(String(format: "%.1f", stats.length)) мм") }
                                    HStack { Text("Высота (Z)"); Spacer(); Text("\(String(format: "%.1f", stats.height)) мм") }
                                    HStack { Text("Слои"); Spacer(); Text("\(stats.numLayers)") }
                                    HStack { Text("Объем"); Spacer(); Text("\(String(format: "%.1f", stats.volume)) мм³") }
                                }
                                .foregroundColor(.primary)
                            } else if !appState.rawPoints.isEmpty {
                                Text("Нажмите 'Рассчитать'").foregroundColor(.secondary)
                            }
                        }
                        
                        Section(header: Text("Лог")) {
                            ForEach(appState.logMessages.suffix(5), id: \.self) { msg in
                                Text(msg).font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                    .navigationTitle("GCode Viewer")
                }
                .tabItem { Label("Данные", systemImage: "list.bullet") }
            }
            
            if showSettings {
                SettingsOverlayView(appState: appState, isPresented: $showSettings)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
                    .zIndex(10)
            }
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [UTType(filenameExtension: "gcode") ?? .data, UTType(filenameExtension: "nc") ?? .data],
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                if let url = urls.first {
                    if url.startAccessingSecurityScopedResource() {
                        appState.isAccessingSecurityScopedResource = true
                        appState.selectedFileURL = url
                        appState.loadSelectedFile()
                    }
                }
            case .failure(let error): appState.log("Ошибка: \(error.localizedDescription)")
            }
        }
        // При закрытии панели настроек — применяем диаметр
        .onChange(of: showSettings) { isShowing in
            if !isShowing && appState.tubeDiameter != appState.lastAppliedDiameter {
                appState.applyDiameter()
            }
        }
    }
}

struct SettingsOverlayView: View {
    @ObservedObject var appState: AppState
    @Binding var isPresented: Bool
    
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("Настройки").font(.headline).foregroundColor(.white)
                Spacer()
                Button(action: {
                    withAnimation { isPresented = false }
                }) {
                    Image(systemName: "xmark.circle.fill").foregroundColor(.gray).font(.title3)
                }
            }
            
            VStack(alignment: .leading) {
                Text("Толщина трубки: \(String(format: "%.1f", appState.tubeDiameter)) мм")
                    .foregroundColor(.white).font(.subheadline)
                Slider(value: $appState.tubeDiameter, in: 1...10, step: 0.5) { Text("Diameter") }
                    .tint(.blue)
            }
            
            Divider().background(Color.gray)
            
            Text("Материал").foregroundColor(.white).font(.subheadline)
            Picker("Материал", selection: $appState.selectedMaterial) {
                ForEach(MaterialPreset.allCases, id: \.self) { mat in Text(mat.rawValue).tag(mat) }
            }
            .pickerStyle(SegmentedPickerStyle())
            .onChange(of: appState.selectedMaterial) { _ in
                appState.applyMaterial()
            }
            
            Divider().background(Color.gray)
            
            Text("Виды камеры").foregroundColor(.white).font(.subheadline)
            
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                CamBtn(title: "Верх", action: .top, appState: appState, isPresented: $isPresented)
                CamBtn(title: "Низ", action: .bottom, appState: appState, isPresented: $isPresented)
                CamBtn(title: "Фронт", action: .front, appState: appState, isPresented: $isPresented)
                CamBtn(title: "Зад", action: .back, appState: appState, isPresented: $isPresented)
                CamBtn(title: "Лево", action: .left, appState: appState, isPresented: $isPresented)
                CamBtn(title: "Право", action: .right, appState: appState, isPresented: $isPresented)
            }
            
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                CamBtn(title: "ISO 1", action: .iso1, appState: appState, isPresented: $isPresented)
                CamBtn(title: "ISO 2", action: .iso2, appState: appState, isPresented: $isPresented)
                CamBtn(title: "ISO 3", action: .iso3, appState: appState, isPresented: $isPresented)
                CamBtn(title: "ISO 4", action: .iso4, appState: appState, isPresented: $isPresented)
            }
            
            Divider().background(Color.gray)
            
            // КНОПКА ЗАПИИСИ
            Button(action: {
                isPresented = false // Скрываем панель перед записью!
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                    appState.recordVideo()
                }
            }) {
                HStack {
                    Image(systemName: appState.isRecording ? "stop.circle.fill" : "video.circle.fill")
                    Text(appState.isRecording ? "Остановить" : "Запись 360°")
                }
                .frame(maxWidth: .infinity)
                .foregroundColor(appState.isRecording ? .red : .white)
                .padding(10)
                .background(appState.isRecording ? Color.white.opacity(0.2) : Color.red.opacity(0.6))
                .cornerRadius(10)
            }
            .disabled(appState.rawPoints.isEmpty)
            
            Spacer()
        }
        .padding(20)
        .frame(maxWidth: 300, maxHeight: .infinity)
        .background(Color.black.opacity(0.85))
        .cornerRadius(20)
        .shadow(radius: 10)
        .padding(.top, 50)
        .padding(.bottom, 50)
        .padding(.leading, 10)
    }
}

struct CamBtn: View {
    let title: String
    let action: CameraAction
    @ObservedObject var appState: AppState
    @Binding var isPresented: Bool
    
    var body: some View {
        Button(action: {
            isPresented = false // Скрываем панель
            appState.cameraAction = action
        }) {
            Text(title)
                .font(.caption)
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding(8)
                .background(Color.blue.opacity(0.3))
                .cornerRadius(8)
        }
    }
}
