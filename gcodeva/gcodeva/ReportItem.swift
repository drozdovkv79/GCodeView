import Foundation
import zlib

// MARK: - Структуры данных

struct ReportItem {
    let number: Int
    let productCode: String      // Код изделия (например, P0.1_93-93)
    let fileName: String
    let fileDate: String
    let width: Float
    let length: Float
    let height: Float
    let numLayers: Int
    let printSpeed: Float
    let imageData: Data
    let imageWidth: Int
    let imageHeight: Int
}

struct ReportSummary {
    let assignmentNumber: String
    let date: String
    let deadlineDate: String
    let totalItems: Int
    let totalAreaSqm: Double
    let location: String
    let executor: String
    let customer: String
    let contactPerson: String
    let directorName: String
}

// MARK: - Data extension (Little-Endian)

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

// MARK: - Минимальный ZIP (метод STORE)

private class SimpleZipWriter {
    private var entries: [(path: String, data: Data)] = []
    func addFile(path: String, data: Data) { entries.append((path, data)) }
    
    func createZip() -> Data {
        var result = Data()
        var centralDir = Data()
        var offset = 0
        
        for entry in entries {
            let pathData = entry.path.data(using: .utf8)!
            let crc = computeCRC32(entry.data)
            let size = UInt32(entry.data.count)
            let pathLen = UInt16(pathData.count)
            
            result.appendUInt32(0x04034B50); result.appendUInt16(20); result.appendUInt16(0); result.appendUInt16(0)
            result.appendUInt16(0); result.appendUInt16(0); result.appendUInt32(crc)
            result.appendUInt32(size); result.appendUInt32(size); result.appendUInt16(pathLen); result.appendUInt16(0)
            result.append(pathData); result.append(entry.data)
            
            centralDir.appendUInt32(0x02014B50); centralDir.appendUInt16(20); centralDir.appendUInt16(20)
            centralDir.appendUInt16(0); centralDir.appendUInt16(0); centralDir.appendUInt16(0); centralDir.appendUInt16(0)
            centralDir.appendUInt32(crc); centralDir.appendUInt32(size); centralDir.appendUInt32(size)
            centralDir.appendUInt16(pathLen); centralDir.appendUInt16(0); centralDir.appendUInt16(0)
            centralDir.appendUInt16(0); centralDir.appendUInt32(0); centralDir.appendUInt32(UInt32(offset))
            centralDir.append(pathData)
            offset = result.count
        }
        
        let cdOffset = result.count
        result.append(centralDir)
        result.appendUInt32(0x06054B50); result.appendUInt16(0); result.appendUInt16(0)
        result.appendUInt16(UInt16(entries.count)); result.appendUInt16(UInt16(entries.count))
        result.appendUInt32(UInt32(centralDir.count)); result.appendUInt32(UInt32(cdOffset)); result.appendUInt16(0)
        return result
    }
    
    private func computeCRC32(_ data: Data) -> UInt32 {
        return data.withUnsafeBytes { ptr in
            guard let base = ptr.baseAddress else { return 0 }
            return UInt32(crc32(0, base.assumingMemoryBound(to: UInt8.self), UInt32(data.count)))
        }
    }
}

// MARK: - Генератор DOCX

class ReportGenerator {
    private static let maxImageWidthEMU = 2_400_000 // ~6.6 см (чтобы идеально влезть в колонку "Файл")
    
    static func generate(items: [ReportItem], summary: ReportSummary) -> Data {
        let zip = SimpleZipWriter()
        zip.addFile(path: "[Content_Types].xml", data: contentTypesXML.data(using: .utf8)!)
        zip.addFile(path: "_rels/.rels", data: rootRelsXML.data(using: .utf8)!)
        zip.addFile(path: "word/styles.xml", data: stylesXML.data(using: .utf8)!)
        
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
        
        zip.addFile(path: "word/document.xml", data: buildDocument(items: items, summary: summary).data(using: .utf8)!)
        return zip.createZip()
    }
    
    // MARK: - Статические шаблоны XML
    
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
    <w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:sz w:val="22"/></w:rPr>
  </w:style>
</w:styles>
"""
    
    // MARK: - XML Хелперы
    
    private static func esc(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
    }
    
    private static func p(_ text: String, bold: Bool = false, fontSize: Int = 22, align: String? = nil, spaceAfter: Int = 0) -> String {
        let pPr = (align != nil) ? "<w:pPr><w:jc w:val=\"\(align!)\"/><w:spacing w:after=\"\(spaceAfter)\"/></w:pPr>" : "<w:pPr><w:spacing w:after=\"\(spaceAfter)\"/></w:pPr>"
        let rPr = bold ? "<w:rPr><w:b/><w:sz w:val=\"\(fontSize)\"/><w:szCs w:val=\"\(fontSize)\"/></w:rPr>" : "<w:rPr><w:sz w:val=\"\(fontSize)\"/><w:szCs w:val=\"\(fontSize)\"/></w:rPr>"
        return "<w:p>\(pPr)<w:r>\(rPr)<w:t xml:space=\"preserve\">\(esc(text))</w:t></w:r></w:p>"
    }
    
    private static func pageBreak() -> String { "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>" }
    
    // Ячейка таблицы с заданной шириной
    private static func tc(content: String, width: Int, bold: Bool = false, vAlign: String = "top") -> String {
        let vMerge = vAlign == "top" ? "<w:vAlign w:val=\"top\"/>" : ""
        let rPr = bold ? "<w:rPr><w:b/></w:rPr>" : ""
        return "<w:tc><w:tcPr><w:tcW w:w=\"\(width)\" w:type=\"dxa\"/>\(vMerge)</w:tcPr>\(content)</w:tc>"
    }
    
    // Изображение для вставки в таблицу
    private static func imageInline(imageIndex: Int, imgW: Int, imgH: Int, docPrId: Int) -> String {
        let aspect = Double(imgH) / Double(max(imgW, 1))
        var emuW = maxImageWidthEMU
        var emuH = Int(Double(emuW) * aspect)
        if emuH > 3_000_000 { emuH = 3_000_000; emuW = Int(Double(emuH) / aspect) }
        
        return """
<w:p><w:pPr><w:jc w:val="left"/><w:spacing w:before="100" w:after="100"/></w:pPr><w:r>\
<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">\
<wp:extent cx="\(emuW)" cy="\(emuH)"/>\
<wp:docPr id="\(docPrId)" name="Picture \(docPrId)"/>\
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">\
<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="image\(imageIndex).png"/><pic:cNvPicPr/></pic:nvPicPr>\
<pic:blipFill><a:blip r:embed="rIdImg\(imageIndex)"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>\
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="\(emuW)" cy="\(emuH)"/></a:xfrm>\
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>\
</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
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
        
        // ═══════ СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ ═══════
        xml += p("Задание на 3Д-печать изделий \(esc(summary.assignmentNumber))", bold: true, fontSize: 28, align: "center", spaceAfter: 400)
        
        var titleRows = ""
        titleRows += "<w:tr>" + tc(content: p("Номер задания", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(esc(summary.assignmentNumber), spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Дата задания", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(summary.date, spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Плановый срок выполнения", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(summary.deadlineDate, spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Количество готовых изделий, всего шт.", bold: true, spaceAfter: 60), width: 3500) + tc(content: p("\(summary.totalItems) шт", spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Количество готовых изделий, всего м2", bold: true, spaceAfter: 60), width: 3500) + tc(content: p("\(String(format: "%.2f", summary.totalAreaSqm)) м2 (расчетная величина)", spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Видов изделий, шт", bold: true, spaceAfter: 60), width: 3500) + tc(content: p("\(summary.totalItems) шт", spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Адрес поставки/монтажа", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(esc(summary.location), spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Исполнитель", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(esc(summary.executor), spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Заказчик", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(esc(summary.customer), spaceAfter: 60), width: 6000) + "</w:tr>"
        titleRows += "<w:tr>" + tc(content: p("Контактное лицо", bold: true, spaceAfter: 60), width: 3500) + tc(content: p(esc(summary.contactPerson), spaceAfter: 60), width: 6000) + "</w:tr>"
        
        xml += """
<w:tbl><w:tblPr><w:tblW w:w="9500" w:type="dxa"/>
<w:tblBorders><w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/><w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>
<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/><w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>
<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/><w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/></w:tblBorders></w:tblPr>
\(titleRows)</w:tbl>
"""
        
        xml += p("", spaceAfter: 600)
        xml += p("Руководитель направления, СБЕР\t\t\t\(esc(summary.directorName))", spaceAfter: 200)
        xml += p("", spaceAfter: 200)
        xml += p("Приложение:", bold: true, spaceAfter: 100)
        xml += p("Детализация по изделиям для печати на \(items.count) \(rusPages(items.count))", spaceAfter: 200)
        
        // ═══════ СТРАНИЦА 2+: ТАБЛИЦА ИЗДЕЛИЙ ═══════
        xml += pageBreak()
        xml += p("Перечень изделий в задании", bold: true, fontSize: 24, spaceAfter: 200)
        
        // Заголовок таблицы (7 колонок)
        let colWidths = [500, 1300, 3800, 1500, 1000, 500, 900]
        var headerRow = "<w:tr>"
        let headers = ["№", "Код изделия", "Файл", "Параметры изделия", "Требования к пост обработке\\упаковке", "Кол-во", "Согласования"]
        for (i, h) in headers.enumerated() {
            headerRow += tc(content: p(h, bold: true, fontSize: 20, spaceAfter: 0), width: colWidths[i], vAlign: "center")
        }
        headerRow += "</w:tr>"
        
        var itemsRows = ""
        for (idx, item) in items.enumerated() {
            let dimsStr = "\(fmt(item.height)) × \(fmt(item.length)) × \(fmt(item.width)) мм"
            
            // Колонка 3: Файл (Наименование, Дата, Габариты, Форма, Визуал+Картинка, Вид обработки, Маркировка)
            var fileCellContent = ""
            fileCellContent += p("Наименование файла: \(esc(item.fileName))", fontSize: 20, spaceAfter: 40)
            fileCellContent += p("Дата файла: \(item.fileDate)", fontSize: 20, spaceAfter: 40)
            fileCellContent += p("Габаритные размеры изделия (В*Д*Ш): \(dimsStr)", fontSize: 20, spaceAfter: 40)
            fileCellContent += p("Форма: сдвоенная плоская панель «вязанка» без паттерна", fontSize: 20, spaceAfter: 40)
            fileCellContent += p("Визуал:", bold: true, fontSize: 20, spaceAfter: 40)
            fileCellContent += imageInline(imageIndex: idx + 1, imgW: item.imageWidth, imgH: item.imageHeight, docPrId: 100 + idx)
            fileCellContent += p("Вид обработки:\n- подрезка сверху 6 мм\n- подрезка снизу 9 мм (убрать юбку)", fontSize: 20, spaceAfter: 40)
            fileCellContent += p("Маркировка: да", fontSize: 20, spaceAfter: 0)
            
            // Колонка 4: Параметры изделия
            var paramsContent = ""
            paramsContent += p("Толщина слоя: 3 мм", fontSize: 20, spaceAfter: 40)
            paramsContent += p("Материал: PETG GF", fontSize: 20, spaceAfter: 40)
            paramsContent += p("Цвет: RAL1013", fontSize: 20, spaceAfter: 40)
            paramsContent += p("Параметры печати:", bold: true, fontSize: 20, spaceAfter: 40)
            paramsContent += p("скорость \(fmt(item.printSpeed))мм/с\nперемычка 250мм\nобдув 0%\nтемпература 160-210грд", fontSize: 20, spaceAfter: 0)
            
            // Колонка 5: Требования
            var reqContent = p("- резка перемычки для получения готовых изделий\n- подрезка сверху 6 мм\n- подрезка снизу 9 мм", fontSize: 20, spaceAfter: 0)
            
            // Колонка 7: Согласования
            let agreeContent = p("Дроздов К", fontSize: 20, spaceAfter: 0)
            
            itemsRows += "<w:tr>"
            itemsRows += tc(content: p("\(item.number)", fontSize: 20, align: "center", spaceAfter: 0), width: colWidths[0], vAlign: "top")
            itemsRows += tc(content: p(esc(item.productCode), fontSize: 20, spaceAfter: 0), width: colWidths[1], vAlign: "top")
            itemsRows += tc(content: fileCellContent, width: colWidths[2], vAlign: "top")
            itemsRows += tc(content: paramsContent, width: colWidths[3], vAlign: "top")
            itemsRows += tc(content: reqContent, width: colWidths[4], vAlign: "top")
            itemsRows += tc(content: p("1", fontSize: 20, align: "center", spaceAfter: 0), width: colWidths[5], vAlign: "top")
            itemsRows += tc(content: agreeContent, width: colWidths[6], vAlign: "top")
            itemsRows += "</w:tr>"
        }
        
        // Собираем таблицу изделий
        xml += """
<w:tbl><w:tblPr><w:tblW w:w="9500" w:type="dxa"/><w:tblLayout w:type="fixed"/>
<w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/><w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/><w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tblBorders></w:tblPr>
<w:tblGrid>
<w:gridCol w:w="\(colWidths[0])"/><w:gridCol w:w="\(colWidths[1])"/><w:gridCol w:w="\(colWidths[2])"/>
<w:gridCol w:w="\(colWidths[3])"/><w:gridCol w:w="\(colWidths[4])"/><w:gridCol w:w="\(colWidths[5])"/>
<w:gridCol w:w="\(colWidths[6])"/>
</w:tblGrid>
\(headerRow)\(itemsRows)
</w:tbl>
"""
        
        xml += "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" w:left=\"1134\" w:header=\"720\" w:footer=\"720\" w:gutter=\"0\"/></w:sectPr>"
        xml += "</w:body>\n</w:document>"
        return xml
    }
    
    private static func fmt(_ f: Float) -> String { String(format: "%.0f", f) }
    private static func rusPages(_ n: Int) -> String {
        let abs = n % 100, last = abs % 10
        if abs > 10 && abs < 20 { return "страницах" }
        if last == 1 { return "страницу" }
        if last >= 2 && last <= 4 { return "страницы" }
        return "страницах"
    }
    
    static func pngDimensions(from data: Data) -> (width: Int, height: Int) {
        guard data.count >= 24, data[0] == 0x89, data[1] == 0x50 else { return (1200, 800) }
        let w = data.withUnsafeBytes { $0.load(fromByteOffset: 16, as: UInt32.self).bigEndian }
        let h = data.withUnsafeBytes { $0.load(fromByteOffset: 20, as: UInt32.self).bigEndian }
        return (Int(w), Int(h))
    }
}
