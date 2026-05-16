//
//  GCodePoint.swift
//  gcodeva
//
//  Created by Костя Дроздов on 16.05.2026.
//


import Foundation
import simd

struct GCodePoint {
    var x: Float = 0
    var y: Float = 0
    var z: Float = 0
    var e: Float = 0
    var feedRate: Float = 0
    var layer: Int = 0
    var isExtrusion: Bool = false
}

struct GCodeStats {
    var totalPoints: Int = 0
    var extrusionPoints: Int = 0
    var travelPoints: Int = 0
    
    var width: Float = 0
    var length: Float = 0
    var height: Float = 0
    
    var numLayers: Int = 0
    var totalMaterial: Float = 0
    var volume: Float = 0
    
    var maxX: Float = 0
    var maxY: Float = 0
    var maxZ: Float = 0
    var maxSpeed: Float = 0
}

class AppState: ObservableObject {
    @Published var files: [URL] = []
    @Published var selectedFile: URL?
    @Published var points: [GCodePoint] = []
    @Published var stats: GCodeStats?
    @Published var isLoading: Bool = false
    @Published var progress: Double = 0
    @Published var logMessages: [String] = []
    
    @Published var tubeDiameter: Float = 0.4
    @Published var modelColor: Color = Color(hex: "#e9e5ce")!
    
    func log(_ message: String) {
        DispatchQueue.main.async {
            let time = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
            self.logMessages.append("[\(time)] \(message)")
        }
    }
}