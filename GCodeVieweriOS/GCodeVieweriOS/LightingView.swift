//
//  LightingView.swift
//  gcodeva
//
//  Created by Костя Дроздов on 01.06.2026.
//


import SwiftUI

// MARK: - Панель управления освещением

struct LightingView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {

            // ── Пресеты ────────────────────────────────────────────────────
            Text("Preset")
                .font(.caption).foregroundColor(.secondary)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 5) {
                
                /*ForEach(LightingPreset.allCases) { preset in
                    let isActive = appState.lightingPreset == preset
                    Button(preset.rawValue) {
                        appState.applyLightingPreset(preset)
                    }
                    .buttonStyle(isActive ? .borderedProminent : .bordered)
                    .controlSize(.small)
                }*/
                ForEach(Array(LightingPreset.allCases.enumerated()), id: \.offset) { index, preset in
                    let isActive = appState.lightingPreset == preset
                    Button(preset.rawValue) {
                        appState.applyLightingPreset(preset)
                    }
                    .buttonStyle(PlainButtonStyle())
                    .padding(6)
                    .frame(maxWidth: .infinity)
                    .background(isActive ? Color.blue : Color.gray.opacity(0.15))
                    .foregroundColor(isActive ? .white : .primary)
                    .cornerRadius(6)
                }
                
            }

            // Подсказка по активному пресету
            Text(appState.lightingPreset.label)
                .font(.caption2)
                .foregroundColor(.secondary)
                .padding(.bottom, 2)

            Divider()

            // ── Слайдеры ────────────────────────────────────────────────────

            // Ambient
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("Ambient").font(.caption)
                    Spacer()
                    Text(String(format: "%.2f", appState.lightingAmbient))
                        .font(.caption).foregroundColor(.secondary).frame(width: 35, alignment: .trailing)
                }
                Slider(value: $appState.lightingAmbient, in: 0.0...0.6, step: 0.01)
                    .onChange(of: appState.lightingAmbient) { appState.applyLighting() }
                Text("↑ Выше = плоский вид. Для рельефа держи < 0.15")
                    .font(.caption2).foregroundColor(.secondary)
            }

            // Главный источник — интенсивность
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("Main light").font(.caption)
                    Spacer()
                    Text(String(format: "%.2f", appState.lightingMainIntensity))
                        .font(.caption).foregroundColor(.secondary).frame(width: 35, alignment: .trailing)
                }
                Slider(value: $appState.lightingMainIntensity, in: 0.2...3.0, step: 0.05)
                    .onChange(of: appState.lightingMainIntensity) { appState.applyLighting() }
            }

            // Горизонтальный угол
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("H-angle").font(.caption)
                    Spacer()
                    Text(String(format: "%.0f°", appState.lightingAngleH))
                        .font(.caption).foregroundColor(.secondary).frame(width: 35, alignment: .trailing)
                }
                Slider(value: $appState.lightingAngleH, in: -180...180, step: 1)
                    .onChange(of: appState.lightingAngleH) { appState.applyLighting() }
                Text("0°= слева · 90°= спереди · 180°= справа")
                    .font(.caption2).foregroundColor(.secondary)
            }

            // Угол возвышения — ключевой для рельефа
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("Elevation").font(.caption)
                    Spacer()
                    Text(String(format: "%.0f°", appState.lightingAngleV))
                        .font(.caption).foregroundColor(.secondary).frame(width: 35, alignment: .trailing)
                }
                Slider(value: $appState.lightingAngleV, in: 2...80, step: 1)
                    .onChange(of: appState.lightingAngleV) { appState.applyLighting() }
                Text("↓ Ниже = скользящий свет = глубже рельеф. 5–10° оптимально")
                    .font(.caption2).foregroundColor(.secondary)
            }

            // Заполняющий источник
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("Fill light").font(.caption)
                    Spacer()
                    Text(String(format: "%.2f", appState.lightingFillIntensity))
                        .font(.caption).foregroundColor(.secondary).frame(width: 35, alignment: .trailing)
                }
                Slider(value: $appState.lightingFillIntensity, in: 0...0.8, step: 0.01)
                    .onChange(of: appState.lightingFillIntensity) { appState.applyLighting() }
                Text("Заполняющий свет с противоположной стороны")
                    .font(.caption2).foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}
