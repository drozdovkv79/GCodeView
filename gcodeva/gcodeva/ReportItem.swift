import Foundation
import zlib
import CoreImage

// MARK: - Структуры данных отчёта

struct ReportItem {
    let number: Int
    let fileName: String
    let fileSize: Int64
    let fileDate: String
    let width: Float      // Ширина (X) мм
    let length: Float     // Длина (Y) мм
    let height: Float     // Высота (Z) мм
    let numLayers: Int
    let extrusionPoints: Int
    let printSpeed: Float // мм/с
    let estimatedTimeHours: Float
    let imageData: Data
    let imageWidth: Int
    let imageHeight: Int
}

struct ReportSummary {
    let assignmentNumber: String
    let date: String
    let deadlineDate: String
    let totalFiles: Int
    let totalSizeBytes: Int64
    let totalItems: Int
    let totalAreaSqm: Double
    let location: String
    let executor: String
    let customer: String
    let contactPerson: String
}

// MARK: - Data extension для записи little-endian целых

private extension Data {
    mutating func appendUInt32(_ value: UInt32) {
        var v = value.littleEndian
        append(Data(bytes: &v, count: 4))
    }
    mutating func appendUInt16(_ value: UInt16) {
        var v = value.littleEndian
        append(Data(bytes: &v, count: 2))
    }
}

// MARK: - Минимальный ZIP-архиватор (метод STORE, без сжатия)

private class SimpleZipWriter {
    private var entries: [(path: String, data: Data)] = []

    func addFile(path: String, data: Data) {
        entries.append((path, data))
    }

    func createZip() -> Data {
        var result = Data()
        var centralDir = Data()
        var offset = 0

        for entry in entries {
            let pathData = entry.path.data(using: .utf8)!
            let crc = computeCRC32(entry.data)
            let size = UInt32(entry.data.count)
            let pathLen = UInt16(pathData.count)

            // --- Local file header (30 байт + путь) ---
            result.appendUInt32(0x04034B50)  // сигнатура
            result.appendUInt16(20)          // версия
            result.appendUInt16(0)           // флаги
            result.appendUInt16(0)           // сжатие: STORE
            result.appendUInt16(0)           // время модификации
            result.appendUInt16(0)           // дата модификации
            result.appendUInt32(crc)
            result.appendUInt32(size)        // сжатый размер
            result.appendUInt32(size)        // исходный размер
            result.appendUInt16(pathLen)
            result.appendUInt16(0)           // extra field
            result.append(pathData)
            result.append(entry.data)

            // --- Central directory header (46 байт + путь) ---
            centralDir.appendUInt32(0x02014B50)
            centralDir.appendUInt16(20)      // версия создания
            centralDir.appendUInt16(20)      // версия извлечения
            centralDir.appendUInt16(0)
            centralDir.appendUInt16(0)
            centralDir.appendUInt16(0)
            centralDir.appendUInt16(0)
            centralDir.appendUInt32(crc)
            centralDir.appendUInt32(size)
            centralDir.appendUInt32(size)
            centralDir.appendUInt16(pathLen)
            centralDir.appendUInt16(0)
            centralDir.appendUInt16(0)       // длина комментария
            centralDir.appendUInt16(0)       // номер диска
            centralDir.appendUInt16(0)       // внутренние атрибуты
            centralDir.appendUInt32(0)       // внешние атрибуты
            centralDir.appendUInt32(UInt32(offset))
            centralDir.append(pathData)

            offset = result.count
        }

        let cdOffset = result.count
        result.append(centralDir)

        // --- End of central directory record ---
        result.appendUInt32(0x06054B50)
        result.appendUInt16(0)
        result.appendUInt16(0)
        result.appendUInt16(UInt16(entries.count))
        result.appendUInt16(UInt16(entries.count))
        result.appendUInt32(UInt32(centralDir.count))
        result.appendUInt32(UInt32(cdOffset))
        result.appendUInt16(0)

        return result
    }

    private func computeCRC32(_ data: Data) -> UInt32 {
        return data.withUnsafeBytes { ptr in
            guard let base = ptr.baseAddress else { return 0 }
            return UInt32(crc32(0, base.assumingMemoryBound(to: UInt8.self), UInt32(data.count)))
        }
    }
}

// MARK: - Генератор DOCX-отчёта

class ReportGenerator {

    // EMU: 1 cm = 360 000 EMU; A4 с полями 2 см → доступно 17 см по ширине, ~25.7 см по высоте
    private static let maxImageWidthEMU  = 5_400_000   // 15 cm
    private static let maxImageHeightEMU = 7_200_000   // 20 cm

    // MARK: - Точка входа

    static func generate(items: [ReportItem], summary: ReportSummary) -> Data {
        let zip = SimpleZipWriter()

        zip.addFile(path: "[Content_Types].xml", data: contentTypesXML.data(using: .utf8)!)
        zip.addFile(path: "_rels/.rels",        data: rootRelsXML.data(using: .utf8)!)
        zip.addFile(path: "word/styles.xml",    data: stylesXML.data(using: .utf8)!)

        for (i, item) in items.enumerated() {
            zip.addFile(path: "word/media/image\(i + 1).png", data: item.imageData)
        }

        var docRels = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
"""
        for i in 0..<items.count {
            docRels += "  <Relationship Id=\"rIdImg\(i + 1)\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" Target=\"media/image\(i + 1).png\"/>\n"
        }
        docRels += "</Relationships>"
        zip.addFile(path: "word/_rels/document.xml.rels", data: docRels.data(using: .utf8)!)

        let documentXML = buildDocument(items: items, summary: summary)
        zip.addFile(path: "word/document.xml", data: documentXML.data(using: .utf8)!)

        return zip.createZip()
    }

    // MARK: - Статические XML-шаблоны

    private static let contentTypesXML = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml"  ContentType="application/xml"/>
  <Default Extension="png"  ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml"    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>
"""

    private static let rootRelsXML = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

    private static let stylesXML = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:rPr>
      <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
      <w:sz w:val="24"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:jc w:val="center"/><w:spacing w:before="240" w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="200" w:after="100"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>
  </w:style>
</w:styles>
"""

    // MARK: - XML-хелперы

    private static func esc(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }

    /// Абзац с опциональным жирным, размером шрифта и выравниванием
    private static func p(_ text: String,
                          bold: Bool = false,
                          fontSize: Int? = nil,
                          align: String? = nil,
                          spaceBefore: Int? = nil,
                          spaceAfter: Int? = nil) -> String {
        var pPrParts: [String] = []
        if let a = align        { pPrParts.append("<w:jc w:val=\"\(a)\"/>") }
        if let b = spaceBefore   { pPrParts.append("<w:spacing w:before=\"\(b)\"/>") }
        if let a = spaceAfter    { pPrParts.append("<w:spacing w:after=\"\(a)\"/>") }
        let pPr = pPrParts.isEmpty ? "" : "<w:pPr>\(pPrParts.joined())</w:pPr>"

        var rPrParts: [String] = []
        if bold                { rPrParts.append("<w:b/>") }
        if let s = fontSize     { rPrParts.append("<w:sz w:val=\"\(s)\"/><w:szCs w:val=\"\(s)\"/>") }
        let rPr = rPrParts.isEmpty ? "" : "<w:rPr>\(rPrParts.joined())</w:rPr>"

        return "<w:p>\(pPr)<w:r>\(rPr)<w:t xml:space=\"preserve\">\(esc(text))</w:t></w:r></w:p>"
    }

    private static func pageBreak() -> String {
        "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"
    }

    /// Строка таблицы из двух ячеек (label — value)
    private static func tableRow2(label: String, value: String, labelW: Int = 3500, valueW: Int = 5500) -> String {
        """
<w:tr>
  <w:tc><w:tcPr><w:tcW w:w="\(labelW)" w:type="dxa"/></w:tcPr>\
\(p(label, bold: true))</w:tc>
  <w:tc><w:tcPr><w:tcW w:w="\(valueW)" w:type="dxa"/></w:tcPr>\
\(p(value))</w:tc>
</w:tr>
"""
    }

    /// Встраивание PNG-изображения
    private static func imageInline(imageIndex: Int,
                                   imgW: Int, imgH: Int,
                                   docPrId: Int) -> String {
        let aspect = Double(imgH) / Double(max(imgW, 1))
        var emuW = maxImageWidthEMU
        var emuH = Int(Double(emuW) * aspect)
        if emuH > maxImageHeightEMU {
            emuH = maxImageHeightEMU
            emuW = Int(Double(emuH) / aspect)
        }

        return """
<w:p>
  <w:pPr><w:jc w:val="center"/><w:spacing w:before="200" w:after="200"/></w:pPr>
  <w:r>
    <w:drawing>
      <wp:inline distT="0" distB="0" distL="0" distR="0">
        <wp:extent cx="\(emuW)" cy="\(emuH)"/>
        <wp:docPr id="\(docPrId)" name="Picture \(docPrId)"/>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic>
              <pic:nvPicPr>
                <pic:cNvPr id="0" name="image\(imageIndex).png"/>
                <pic:cNvPicPr/>
              </pic:nvPicPr>
              <pic:blipFill>
                <a:blip r:embed="rIdImg\(imageIndex)"/>
                <a:stretch><a:fillRect/></a:stretch>
              </pic:blipFill>
              <pic:spPr>
                <a:xfrm><a:off x="0" y="0"/><a:ext cx="\(emuW)" cy="\(emuH)"/></a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
              </pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:inline>
    </w:drawing>
  </w:r>
</w:p>"""
    }

    /// Обёртка таблицы с границами
    private static func tableWrap(_ rows: String) -> String {
        """
<w:tbl>
  <w:tblPr>
    <w:tblW w:w="9000" w:type="dxa"/>
    <w:tblBorders>
      <w:top     w:val="single" w:sz="4" w:space="0" w:color="000000"/>
      <w:left    w:val="single" w:sz="4" w:space="0" w:color="000000"/>
      <w:bottom  w:val="single" w:sz="4" w:space="0" w:color="000000"/>
      <w:right   w:val="single" w:sz="4" w:space="0" w:color="000000"/>
      <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>
      <w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>
    </w:tblBorders>
  </w:tblPr>
\(rows)
</w:tbl>
"""
    }

    // MARK: - Построение document.xml

    private static func buildDocument(items: [ReportItem], summary: ReportSummary) -> String {
        var xml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
            xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
<w:body>
"""

        // ═══════════ СТРАНИЦА 1: ОБЩИЕ ДАННЫЕ ═══════════
        xml += p("Задание на 3Д-печать изделий \(esc(summary.assignmentNumber))",
                 bold: true, fontSize: 32, align: "center", spaceAfter: 300)

        xml += p("Общие данные", bold: true, fontSize: 28, spaceBefore: 200, spaceAfter: 100)

        let totalSizeStr = ByteCountFormatter.string(fromByteCount: summary.totalSizeBytes, countStyle: .file)
        let areaStr      = String(format: "%.2f", summary.totalAreaSqm)

        var summaryRows = ""
        summaryRows += tableRow2(label: "Номер задания",                value: summary.assignmentNumber)
        summaryRows += tableRow2(label: "Дата задания",                 value: summary.date)
        summaryRows += tableRow2(label: "Плановый срок выполнения",     value: summary.deadlineDate)
        summaryRows += tableRow2(label: "Количество файлов gcode",      value: "\(summary.totalFiles) шт")
        summaryRows += tableRow2(label: "Общий размер файлов",          value: totalSizeStr)
        summaryRows += tableRow2(label: "Видов изделий",                value: "\(summary.totalFiles) шт")
        summaryRows += tableRow2(label: "Общая площадь изделий",        value: "\(areaStr) м² (расчетная величина)")
        summaryRows += tableRow2(label: "Адрес поставки/монтажа",       value: summary.location)
        summaryRows += tableRow2(label: "Исполнитель",                  value: summary.executor)
        summaryRows += tableRow2(label: "Заказчик",                     value: summary.customer)
        summaryRows += tableRow2(label: "Контактное лицо",              value: summary.contactPerson)
        xml += tableWrap(summaryRows)

        xml += p("", spaceBefore: 200)
        xml += p("Приложение:", bold: true, spaceBefore: 200)
        xml += p("Детализация по изделиям для печати на \(items.count) \(rusPages(items.count))",
                 spaceAfter: 200)

        // ═══════════ СТРАНИЦЫ 2+: ИЗДЕЛИЯ ═══════════
        for (idx, item) in items.enumerated() {
            xml += pageBreak()

            // Заголовок
            xml += p("Изделие №\(item.number)",
                     bold: true, fontSize: 28, spaceBefore: 100, spaceAfter: 50)
            xml += p("Файл: \(esc(item.fileName))", fontSize: 24, spaceAfter: 100)

            // Таблица параметров
            let dimsStr = "\(fmt(item.height)) × \(fmt(item.length)) × \(fmt(item.width)) мм"
            var rows = ""
            rows += tableRow2(label: "Дата файла",                    value: item.fileDate)
            rows += tableRow2(label: "Размер файла",                  value: ByteCountFormatter.string(fromByteCount: item.fileSize, countStyle: .file))
            rows += tableRow2(label: "Габаритные размеры (В×Д×Ш)",   value: dimsStr)
            rows += tableRow2(label: "Количество слоёв",              value: "\(item.numLayers)")
            rows += tableRow2(label: "Точек экструзии",               value: "\(item.extrusionPoints)")
            rows += tableRow2(label: "Скорость печати",               value: "\(fmt(item.printSpeed)) мм/с")
            rows += tableRow2(label: "Расчётное время печати",        value: "\(fmt(item.estimatedTimeHours)) ч.")
            xml += tableWrap(rows)

            // Скриншот ISO-1
            xml += p("Визуал (ISO-1):", bold: true, spaceBefore: 200, spaceAfter: 100)
            xml += imageInline(imageIndex: idx + 1,
                               imgW: item.imageWidth, imgH: item.imageHeight,
                               docPrId: 100 + idx)
        }

        // Секционные свойства (A4, поля 2 см)
        xml += """
<w:sectPr>
  <w:pgSz w:w="11906" w:h="16838"/>
  <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"
           w:header="720" w:footer="720" w:gutter="0"/>
</w:sectPr>
"""
        xml += "</w:body>\n</w:document>"
        return xml
    }

    // MARK: - Утилиты

    private static func fmt(_ f: Float) -> String {
        String(format: "%.1f", f)
    }

    /// «страницах» / «странице» / «страницу»
    private static func rusPages(_ n: Int) -> String {
        let abs = n % 100
        let last = abs % 10
        if abs > 10 && abs < 20 { return "страницах" }
        if last == 1 { return "страницу" }
        if last >= 2 && last <= 4 { return "страницы" }
        return "страницах"
    }

    /// Извлечь ширину/высоту из PNG-данных (заголовок IHDR)
    static func pngDimensions(from data: Data) -> (width: Int, height: Int) {
        guard data.count >= 24,
              data[0] == 0x89, data[1] == 0x50, data[2] == 0x4E, data[3] == 0x47,
              data[4] == 0x0D, data[5] == 0x0A, data[6] == 0x1A, data[7] == 0x0A
        else { return (1920, 1080) }
        let w = data.withUnsafeBytes { $0.load(fromByteOffset: 16, as: UInt32.self).bigEndian }
        let h = data.withUnsafeBytes { $0.load(fromByteOffset: 20, as: UInt32.self).bigEndian }
        return (Int(w), Int(h))
    }
}