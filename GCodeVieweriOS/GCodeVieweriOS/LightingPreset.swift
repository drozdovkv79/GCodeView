//
//  LightingPreset.swift
//  gcodeva
//
//  Created by Костя Дроздов on 01.06.2026.
//


import Foundation
import SwiftUI

// MARK: - Пресеты освещения

enum LightingPreset: String, CaseIterable, Identifiable {
    case relief   = "Relief"
    case studio   = "Studio"
    case dramatic = "Dramatic"
    case flat     = "Flat"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .relief:   return "Relief (скользящий)"
        case .studio:   return "Studio (нейтральный)"
        case .dramatic: return "Dramatic (контрастный)"
        case .flat:     return "Flat (без теней)"
        }
    }

    // Параметры каждого пресета
    var settings: LightingSettings {
        switch self {

        // ── RELIEF ─────────────────────────────────────────────────────────
        // Главный свет идёт почти горизонтально с левой стороны (~6° над
        // горизонтом). Это «raking light» / «grazing light» — скользящий
        // боковой свет, который даёт длинные тени даже от 1–2 мм рельефа.
        // Ambient намеренно очень низкий, чтобы тени не заполнялись.
        case .relief:
            return LightingSettings(
                ambientIntensity:  0.10,   // очень тёмный ambient → тени глубокие
                mainIntensity:     1.60,   // сильный ключевой свет
                mainAngleH:        0,      // 0° = строго слева
                mainAngleV:        6,      // 6° от горизонта — почти параллельно панели
                fillIntensity:     0.25    // слабый заполняющий справа, чтобы тень не была чёрной
            )

        // ── STUDIO ─────────────────────────────────────────────────────────
        // Классическая трёхточечная студийная схема. Сбалансированная,
        // хороша для общего просмотра геометрии без экстремальных теней.
        case .studio:
            return LightingSettings(
                ambientIntensity:  0.20,
                mainIntensity:     1.10,
                mainAngleH:        -40,   // немного спереди-слева
                mainAngleV:        35,    // 35° — классический студийный угол
                fillIntensity:     0.45
            )

        // ── DRAMATIC ───────────────────────────────────────────────────────
        // Высококонтрастное освещение. Ambient почти нулевой, главный свет
        // очень яркий. Хорошо для фото/видео рендера и экспорта.
        case .dramatic:
            return LightingSettings(
                ambientIntensity:  0.04,
                mainIntensity:     2.20,
                mainAngleH:        60,    // спереди-справа
                mainAngleV:        20,
                fillIntensity:     0.08
            )

        // ── FLAT ───────────────────────────────────────────────────────────
        // Равномерный свет без теней. Подходит для проверки геометрии,
        // когда тени мешают видеть форму.
        case .flat:
            return LightingSettings(
                ambientIntensity:  0.55,
                mainIntensity:     0.65,
                mainAngleH:        0,
                mainAngleV:        45,
                fillIntensity:     0.55
            )
        }
    }
}

// MARK: - Настройки освещения

struct LightingSettings {
    /// Интенсивность рассеянного света (0–1).
    /// Чем ниже — тем темнее тени и контрастнее рельеф.
    var ambientIntensity:  Float

    /// Интенсивность главного направленного источника.
    var mainIntensity:     Float

    /// Горизонтальный угол главного источника (градусы).
    /// 0° = строго слева от модели (ось -X),
    /// 90° = спереди, 180° = справа, -90° = сзади.
    var mainAngleH:        Float

    /// Угол возвышения главного источника над горизонтом (градусы).
    /// Малые значения (3–10°) дают «скользящий» свет — максимальный
    /// контраст рельефа. Большие (40–60°) — мягче, меньше теней.
    var mainAngleV:        Float

    /// Интенсивность заполняющего источника (противоположная сторона).
    var fillIntensity:     Float
}
