//
//  GCodeParser.swift
//  GCodeVieweriOS
//
//  Created by Костя Дроздов on 18.05.2026.
//


import Foundation
import simd

class GCodeParser {
    
    static func parse(file: URL, progress: @escaping (Double) -> Void) -> [GCodePoint] {
        var points: [GCodePoint] = []
        points.reserveCapacity(1_000_000)
        
        guard let data = try? Data(contentsOf: file, options: .alwaysMapped) else { return points }
        
        let totalBytes = data.count
        var lastProgressByte = 0
        let progressStep = totalBytes / 20
        
        var isG1 = false
        var x: Float = 0, y: Float = 0, z: Float = 0, e: Float = 0, f: Float = 0
        var currentLayer = 0
        var lastZ: Float = 0
        
        data.withUnsafeBytes { rawBufferPointer in
            let bytes = rawBufferPointer.bindMemory(to: UInt8.self)
            var lineStart = 0
            
            for i in 0..<totalBytes {
                let byte = bytes[i]
                if byte == 10 || byte == 13 {
                    if i > lineStart {
                        let end = i
                        var idx = lineStart
                        
                        while idx < end && bytes[idx] == 32 { idx += 1 }
                        
                        if idx < end && bytes[idx] == 71 { // 'G'
                            idx += 1
                            if idx < end && (bytes[idx] == 48 || bytes[idx] == 49) {
                                isG1 = bytes[idx] == 49
                                idx += 1
                                if idx < end && (bytes[idx] == 32 || bytes[idx] == 9) {
                                    var posX: Float? = nil, posY: Float? = nil, posZ: Float? = nil, posE: Float? = nil, posF: Float? = nil
                                    
                                    while idx < end {
                                        let c = bytes[idx]
                                        if c == 59 { break }
                                        
                                        if c == 88 || c == 89 || c == 90 || c == 69 || c == 70 {
                                            let param = c
                                            idx += 1
                                            if let result = parseFloat(bytes: bytes, start: idx, end: end) {
                                                switch param {
                                                case 88: posX = result.value
                                                case 89: posY = result.value
                                                case 90: posZ = result.value
                                                case 69: posE = result.value
                                                case 70: posF = result.value
                                                default: break
                                                }
                                                idx += result.length - 1
                                            }
                                        }
                                        idx += 1
                                    }
                                    
                                    if let v = posX { x = v }
                                    if let v = posY { y = v }
                                    if let v = posZ {
                                        z = v
                                        if abs(z - lastZ) > 1.0 {
                                            currentLayer += 1
                                            lastZ = z
                                        }
                                    }
                                    if let v = posE { e = v }
                                    if let v = posF { f = v }
                                    
                                    let hasExtrusion = isG1 && e > 0
                                    points.append(GCodePoint(x: x, y: y, z: z, e: e, feedRate: f, layer: currentLayer, isExtrusion: hasExtrusion))
                                }
                            }
                        }
                    }
                    lineStart = i + 1
                    
                    if i - lastProgressByte > progressStep {
                        lastProgressByte = i
                        progress(Double(i) / Double(totalBytes) * 50.0)
                    }
                }
            }
        }
        return points
    }
    
    @inline(__always)
    private static func parseFloat(bytes: UnsafeBufferPointer<UInt8>, start: Int, end: Int) -> (value: Float, length: Int)? {
        var i = start
        var val: Float = 0
        var sign: Float = 1
        var hasDigits = false
        
        if i < end && bytes[i] == 45 { sign = -1; i += 1 }
        while i < end {
            let c = bytes[i]
            if c >= 48 && c <= 57 {
                val = val * 10 + Float(c - 48)
                hasDigits = true
                i += 1
            } else { break }
        }
        if i < end && bytes[i] == 46 {
            i += 1
            var dec: Float = 0.1
            while i < end {
                let c = bytes[i]
                if c >= 48 && c <= 57 {
                    val += Float(c - 48) * dec
                    dec *= 0.1
                    hasDigits = true
                    i += 1
                } else { break }
            }
        }
        if hasDigits {
            return (sign * val, i - start)
        }
        return nil
    }
}