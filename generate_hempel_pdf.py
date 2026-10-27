#!/usr/bin/env python3
"""
PDF generator for Hempel colors.
Generates two versions:
1. Digital - one large continuous page for screens.
2. Print - paginated A4 landscape version for printers.
"""

import colorsys
import csv
import io
import os
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

SECTIONS = ["Žlutá", "Oranžová", "Červená", "Fialová", "Modrá", "Zelená", "Šedá", "Hnědá", "Černá/bílá"]

# --- BRAND COLORS ---
CORRO_CYAN = colors.Color(0, 199 / 255, 222 / 255)
CORRO_RED = colors.Color(1, 0, 0)
CORRO_GREY = colors.Color(235 / 255, 235 / 255, 235 / 255)


def register_fonts():
    """Register custom fonts if available, fallback to standard fonts."""
    try:
        pdfmetrics.registerFont(TTFont('Arial', 'fonts/arial.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Bold', 'fonts/arialbd.ttf'))
        return 'Arial', 'Arial-Bold'
    except Exception:
        return 'Helvetica', 'Helvetica-Bold'


def rgb_of(rec):
    """Extract RGB tuple from CSV record."""
    try:
        vals = tuple(int(rec[k]) for k in ("RGB_R", "RGB_G", "RGB_B"))
        if all(0 <= x <= 255 for x in vals): return vals
    except Exception:
        pass
    hx = rec.get("HEX", "")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", hx):
        return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
    return 240, 240, 240


def classify(rec):
    """Classify color into a base section."""
    ral = (rec.get("RAL_code") or "").strip()
    ral_digits = ''.join(filter(str.isdigit, ral))

    if len(ral_digits) == 4:
        first_digit = ral_digits[0]
        if first_digit == '1': return "Žlutá"
        if first_digit == '2': return "Oranžová"
        if first_digit == '3': return "Červená"
        if first_digit == '4': return "Fialová"
        if first_digit == '5': return "Modrá"
        if first_digit == '6': return "Zelená"
        if first_digit == '7': return "Šedá"
        if first_digit == '8': return "Hnědá"
        if first_digit == '9': return "Černá/bílá"

    r, g, b = [x / 255 for x in rgb_of(rec)]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    d = h * 360

    if s < .15: return "Černá/bílá" if lum >= .75 or lum <= .20 else "Šedá"
    if 10 <= d < 50 and lum < .45 and s >= .20: return "Hnědá"
    if d >= 345 or d < 15: return "Červená"
    if d < 45: return "Oranžová"
    if d < 62: return "Žlutá"
    if d < 165: return "Zelená"
    if d < 260: return "Modrá"
    if d < 325: return "Fialová"
    return "Červená"


def draw_corrotech_header(c, W, H, mx, font_reg, font_bold):
    """Draw the standard Corrotech header."""
    c.setFont(font_bold, 14)
    c.setFillColor(colors.black)
    c.drawString(mx, H - 25, "HEMPEL – BAREVNÝ CENÍK")

    logo_y = H - 35
    try:
        if os.path.exists("img/corro-pdf.png"):
            c.drawImage("img/corro-pdf.png", W - 180, logo_y + 2, width=127, height=15, preserveAspectRatio=True,
                        mask='auto')
        if os.path.exists("img/hempel-pdf.png"):
            c.drawImage("img/hempel-pdf.png", W - mx - 37.5, logo_y, width=37.5, height=22.5, preserveAspectRatio=True,
                        mask='auto')
    except Exception:
        pass

    c.setStrokeColor(CORRO_CYAN)
    c.setLineWidth(1)
    c.line(mx, H - 40, W - mx, H - 40)

    c.setFont(font_reg, 7)
    c.setFillColor(colors.black)
    c.drawString(mx, H - 50, "Ceny kalkulovány bez DPH")

    # Optional: Info about pricing formula
    c.drawRightString(W - mx, H - 50, "Formát ceny: RAL (Komplet)")
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.gray)
    c.line(mx, H - 54, W - mx, H - 54)


def draw_corrotech_footer(c, W, mx, font_reg, page_str=""):
    """Draw the standard Corrotech footer."""
    y_pos = 15
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.line(mx, y_pos + 8, W - mx, y_pos + 8)

    c.setFont(font_reg, 8)
    c.setFillColor(colors.black)
    company_info = "CORROTECH OSTRAVA s.r.o.  |  Frýdecká 687/406, 719 00 Ostrava - Kunčice  |  +420 734 253 950  |  ostrava@corrotech.com  |  www.corrotech.cz"
    c.drawString(mx, y_pos, company_info)
    c.setFont(font_reg, 6)
    c.setFillColor(colors.gray)
    text_right = f"Strana {page_str}" if page_str else "Generováno automaticky - CORROTECH"
    c.drawRightString(W - mx, y_pos, text_right)


def draw_card(c, rec, x, yb, cw, card_h, count, font_reg, font_bold):
    """Draw an individual color card with pricing logic."""
    c.setFillColor(colors.white if count % 2 == 0 else CORRO_GREY)
    c.setStrokeColor(colors.lightgrey)
    c.setLineWidth(0.5)
    c.rect(x, yb, cw, card_h, fill=1, stroke=1)

    rr, gg, bb = rgb_of(rec)
    c.setFillColor(colors.Color(rr / 255, gg / 255, bb / 255))
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.3)
    c.rect(x + 3, yb + 4, 25, 13, fill=1, stroke=1)

    ral = (rec.get("RAL_code") or "").strip() or "—"
    hempel = (rec.get("Hempel_code") or "").strip() or "—"
    tx = x + 32

    c.setFillColor(colors.black)
    c.setFont(font_bold, 7)
    c.drawString(tx, yb + 13, f"RAL {ral}")
    c.setFont(font_reg, 7)
    c.drawString(tx, yb + 5, f"Hempel {hempel}")

    px = x + cw - 35
    c.setStrokeColor(CORRO_RED)
    c.setLineWidth(0.5)
    c.line(px, yb + 6, x + cw - 3, yb + 6)

    # Calculate and format price: "ral_price (base_price + ral_price)"
    try:
        ral_price = float(rec.get("ral_price", 0))
        base_price = float(rec.get("base_price", 0))
    except ValueError:
        ral_price = 0.0
        base_price = 0.0

    total_price = base_price + ral_price
    if total_price > 0:
        price_text = f"{int(ral_price)} ({int(total_price)})"
    else:
        # Placeholder before DB/CSV is fully populated with prices
        price_text = "Cena"

    c.setFillColor(colors.darkgray)
    c.setFont(font_reg, 5.5)
    c.drawString(px, yb + 13, price_text)


def generate_digital_bytes(groups, font_reg, font_bold):
    """Generate the digital version and return as a byte stream."""
    buffer = io.BytesIO()
    MAX_ITEMS_PER_COL = 40
    columns_data = []
    section_spans = []
    col_idx = 0

    for section in SECTIONS:
        items = groups[section]
        if not items: continue

        start_col = col_idx
        count_cols = 0

        for i in range(0, len(items), MAX_ITEMS_PER_COL):
            columns_data.append(items[i:i + MAX_ITEMS_PER_COL])
            col_idx += 1
            count_cols += 1

        section_spans.append({"name": section, "start": start_col, "count": count_cols})

    total_cols = len(columns_data)
    if total_cols == 0: return buffer.getvalue()

    cw = 115
    card_h = 21
    gap = 6
    mx = 20
    top = 25
    bottom = 30
    header_h = 45
    section_h = 17
    W = (mx * 2) + (total_cols * cw) + ((total_cols - 1) * gap)
    H = top + header_h + section_h + (MAX_ITEMS_PER_COL * card_h) + bottom
    ytop = H - top - header_h

    c = canvas.Canvas(buffer, pagesize=(W, H))
    c.setTitle("HEMPEL – BAREVNÝ CENÍK (DIGITAL)")

    draw_corrotech_header(c, W, H, mx, font_reg, font_bold)
    draw_corrotech_footer(c, W, mx, font_reg)

    for span in section_spans:
        start_x = mx + span["start"] * (cw + gap)
        span_w = (span["count"] * cw) + ((span["count"] - 1) * gap)

        c.setFillColor(CORRO_CYAN)
        c.rect(start_x, ytop - section_h + 2, span_w, section_h - 2, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(font_bold, 8)
        c.drawCentredString(start_x + (span_w / 2.0), ytop - 9, span["name"])

    count = 0
    for i, col_items in enumerate(columns_data):
        x = mx + i * (cw + gap)
        y = ytop - section_h
        for rec in col_items:
            yb = y - card_h
            draw_card(c, rec, x, yb, cw, card_h, count, font_reg, font_bold)
            y -= card_h
            count += 1

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_print_bytes(groups, font_reg, font_bold):
    """Generate the print version and return as a byte stream."""
    buffer = io.BytesIO()
    W, H = landscape(A4)
    mx = 20
    top = 25
    bottom = 30
    header_h = 45
    section_h = 17
    ytop = H - top - header_h

    MAX_COLS = 6
    gap = 6
    card_h = 21
    cw = (W - (2 * mx) - ((MAX_COLS - 1) * gap)) / MAX_COLS

    c = canvas.Canvas(buffer, pagesize=(W, H))
    c.setTitle("HEMPEL – BAREVNÝ CENÍK (TISK)")

    page_num = 1
    is_first_page = True

    def draw_section_head(name, x, yt):
        c.setFillColor(CORRO_CYAN)
        c.rect(x, yt - section_h + 2, cw, section_h - 2, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(font_bold, 8)
        c.drawString(x + 5, yt - 9, name)
        return yt - section_h

    for section in SECTIONS:
        items = groups[section]
        if not items: continue

        if not is_first_page:
            c.showPage()
            page_num += 1
        is_first_page = False

        draw_corrotech_header(c, W, H, mx, font_reg, font_bold)
        draw_corrotech_footer(c, W, mx, font_reg, str(page_num))

        col_idx = 0
        x = mx + col_idx * (cw + gap)
        y = draw_section_head(section, x, ytop)

        count = 0
        for rec in items:
            if y - card_h < bottom:
                col_idx += 1
                if col_idx >= MAX_COLS:
                    c.showPage()
                    page_num += 1
                    draw_corrotech_header(c, W, H, mx, font_reg, font_bold)
                    draw_corrotech_footer(c, W, mx, font_reg, str(page_num))
                    col_idx = 0

                x = mx + col_idx * (cw + gap)
                y = draw_section_head(f"{section} (pokrač.)", x, ytop)

            yb = y - card_h
            draw_card(c, rec, x, yb, cw, card_h, count, font_reg, font_bold)

            y -= card_h
            count += 1

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def get_hempel_pdfs(csv_path="hempel_export/hempel_colors.csv"):
    """
    Main entry point for Streamlit.
    Reads the CSV and returns a dictionary with byte streams of both PDFs.
    """
    font_reg, font_bold = register_fonts()

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))

    groups = {s: [] for s in SECTIONS}
    for rec in records:
        groups[classify(rec)].append(rec)

    for name in SECTIONS:
        groups[name].sort(
            key=lambda r: (1 if not (r.get("RAL_code") or "").strip() else 0,
                           (r.get("RAL_code") or "").strip(),
                           (r.get("Hempel_code") or "").strip())
        )

    digital_bytes = generate_digital_bytes(groups, font_reg, font_bold)
    print_bytes = generate_print_bytes(groups, font_reg, font_bold)

    return {
        "digital": digital_bytes,
        "print": print_bytes
    }