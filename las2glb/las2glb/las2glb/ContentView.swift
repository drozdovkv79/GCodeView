//
//  ContentView.swift
//  las2glb
//
//  Created by Костя Дроздов on 18.07.2026.
//

import SwiftUI

// MARK: - SwiftUI View
struct ContentView: View {
    @State private var vm = ConverterViewModel()
    
    var body: some View {
        VStack(spacing: 15) {
            Text("LAS → GLB Converter")
                .font(.largeTitle).bold()
            
            GroupBox("Пути") {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Input:").frame(width: 60, alignment: .leading)
                        TextField("LAS file", text: $vm.inputPath).textFieldStyle(.roundedBorder)
                        Button("Выбрать") { Task { await vm.selectInput() } }
                    }
                    HStack {
                        Text("Output:").frame(width: 60, alignment: .leading)
                        TextField("GLB file", text: $vm.outputPath).textFieldStyle(.roundedBorder)
                    }
                }
            }
            
            GroupBox("Параметры") {
                HStack {
                    Text("Целевое кол-во точек:")
                    TextField("300000", value: $vm.targetDecimation, format: .number)
                        .frame(width: 120)
                        .textFieldStyle(.roundedBorder)
                    Text("(Рекомендуется 200k-500k)")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            
            HStack {
                Button(vm.isProcessing ? "Обработка..." : "Начать конвертацию") {
                    vm.startConversion()
                }
                .disabled(vm.isProcessing || vm.inputPath.isEmpty)
                .buttonStyle(.borderedProminent)
                
                ProgressView(value: vm.progress)
                    .progressViewStyle(.linear)
                    .frame(width: 300)
            }
            
            Text(vm.status).font(.headline).foregroundStyle(vm.status == "Готово!" ? .green : .primary)
            
            GroupBox("Логи") {
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(vm.logs, id: \.self) { log in
                            Text(log).font(.system(.caption, design: .monospaced))
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: 200)
            }
        }
        .padding(20)
        .frame(minWidth: 700, minHeight: 600)
    }
}
