"""Report exporters written with the standard library only: CSV, XLSX (SpreadsheetML in a zip) and
PDF (a paginated text table in the base-14 Helvetica font).

These cover tabular reports. Anything richer should move to a dedicated library."""

import csv
import io
import zipfile
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from app.core.errors import ValidationFailure

FORMATS = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _cell(value) -> str:  # noqa: ANN001
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.1f}" if value != int(value) else str(int(value))
    if isinstance(value, (list, dict)):
        return str(value)
    return str(value)


def to_csv(title: str, columns: list[str], rows: list[list]) -> bytes:
    out = io.StringIO()
    out.write("﻿")  # byte-order mark, so Excel reads UTF-8 correctly
    writer = csv.writer(out)
    writer.writerow([f"# {title} · generated {datetime.now(UTC).isoformat(timespec='seconds')}"])
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return out.getvalue().encode("utf-8")


def _col_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def to_xlsx(title: str, columns: list[str], rows: list[list]) -> bytes:
    sheet_rows = [columns] + rows
    xml_rows = []
    for r, row in enumerate(sheet_rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_col_letter(c)}{r}"
            style = ' s="1"' if r == 1 else ""
            if isinstance(value, bool):
                cells.append(
                    f'<c r="{ref}" t="inlineStr"{style}><is><t>{"TRUE" if value else "FALSE"}</t></is></c>'  # noqa: E501
                )
            elif isinstance(value, (int, float)) and r > 1:
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"{style}><is><t>{escape(_cell(value))}</t></is></c>'
                )
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    widths = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{min(40, max(12, len(str(c)) + 4))}" customWidth="1"/>'  # noqa: E501
        for i, c in enumerate(columns)
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{widths}</cols><sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(title[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'  # noqa: E501
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        "</styleSheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'  # noqa: E501
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'  # noqa: E501
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'  # noqa: E501
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'  # noqa: E501
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'  # noqa: E501
        "</Relationships>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'  # noqa: E501
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'  # noqa: E501
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/styles.xml", styles)
    return buffer.getvalue()


# --- PDF ---

PAGE_W, PAGE_H = 842, 595  # A4 landscape, so wide tables fit
MARGIN = 36
FONT_SIZE = 8
LINE = 11


def _pdf_text(value: str) -> str:
    # The base-14 fonts use WinAnsi. Characters outside it are replaced, so the stream stays valid.
    safe = _cell(value).encode("cp1252", "replace").decode("cp1252")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def to_pdf(title: str, columns: list[str], rows: list[list]) -> bytes:
    usable = PAGE_W - 2 * MARGIN
    width = usable / max(1, len(columns))
    max_chars = max(6, int(width / (FONT_SIZE * 0.5)))
    pages: list[list[str]] = []
    header = f"{title}  ·  generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    lines_per_page = int((PAGE_H - 2 * MARGIN) / LINE) - 2
    body = [columns] + rows
    for start in range(0, len(body), lines_per_page):
        chunk = body[start : start + lines_per_page]
        ops = [f"BT /F1 11 Tf {MARGIN} {PAGE_H - MARGIN} Td ({_pdf_text(header)}) Tj ET"]
        y = PAGE_H - MARGIN - 2 * LINE
        for index, row in enumerate(chunk):
            font = "F2" if start == 0 and index == 0 else "F1"
            for col, value in enumerate(row):
                text = _cell(value)
                if len(text) > max_chars:
                    text = text[: max_chars - 1] + "…"
                x = MARGIN + col * width
                ops.append(f"BT /{font} {FONT_SIZE} Tf {x:.1f} {y} Td ({_pdf_text(text)}) Tj ET")
            y -= LINE
        pages.append(ops)
    if not pages:
        pages = [[f"BT /F1 11 Tf {MARGIN} {PAGE_H - MARGIN} Td ({_pdf_text(header)}) Tj ET"]]
    return _assemble_pdf(pages)


def _assemble_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    catalog = add("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add("")  # placeholder, filled after the kids are known
    font_regular = add(
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    font_bold = add(
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    page_ids = []
    for ops in pages:
        stream = "\n".join(ops)
        content_id = add(
            f"<< /Length {len(stream.encode('latin-1', 'replace'))} >>\nstream\n{stream}\nendstream"
        )
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            )
        )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode(
        "latin-1"
    )
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)


def render(fmt: str, title: str, columns: list[str], rows: list[list]) -> bytes:
    if fmt == "csv":
        return to_csv(title, columns, rows)
    if fmt == "xlsx":
        return to_xlsx(title, columns, rows)
    if fmt == "pdf":
        return to_pdf(title, columns, rows)
    raise ValidationFailure("format must be csv, xlsx or pdf")
