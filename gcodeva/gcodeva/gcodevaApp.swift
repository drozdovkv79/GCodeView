import SwiftUI

@main
struct gcodevaApp: App {
    @StateObject var appState = AppState()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 1000, minHeight: 600)
                .onOpenURL { url in
                    // Если программе передают файл при запуске
                    if url.pathExtension.lowercased() == "gcode" || url.pathExtension.lowercased() == "nc" {
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
