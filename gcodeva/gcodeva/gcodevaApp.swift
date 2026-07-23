import SwiftUI

// MARK: - 🆕 AppDelegate для доступа к AppState из NSView
class AppDelegate: NSObject, NSApplicationDelegate {
    static var shared = AppDelegate()
    var appState: AppState?
}

@main
struct gcodevaApp: App {
    @StateObject var appState = AppState()
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 1000, minHeight: 600)
                .onAppear {
                    // Передаем состояние в AppDelegate для доступа из CustomSCNView
                    AppDelegate.shared.appState = appState
                }
                .onOpenURL { url in
                    if url.pathExtension.lowercased() == "gcode" {
                        let dir = url.deletingLastPathComponent()
                        appState.currentDirectory = dir
                        appState.loadFilesFromDirectory(dir)
                        appState.selectedFileURL = url
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                            appState.loadSelectedFile()
                        }
                    }
                }
        }
    }
}
