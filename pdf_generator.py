from fpdf import FPDF
import datetime


# -----------------------------------------------------------------------------
# PDF Template Definition
# -----------------------------------------------------------------------------
class KalkulacePDF(FPDF):
    def __init__(self, user_info=None, validity_date= "nevyplněno", *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.user_info = user_info or {
            "name": "Neznámý uživatel",
            "phone": "+420 734 253 950",
            "email": "ostrava@corrotech.com"
        }
        self.validity_date = validity_date

        font_regular = r"C:\Windows\Fonts\arial.ttf"
        font_bold = r"C:\Windows\Fonts\arialbd.ttf"
        self.add_font("Arial", "", font_regular)
        self.add_font("Arial", "B", font_bold)

        self.sum_teor_cena_m2 = 0.0
        self.sum_teor_cena = 0.0
        self.main_loss = 50

    def dashed_line(self, x1, y1, x2, y2, dash_length=1, space_length=1):
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if length == 0:
            return

        dx = (x2 - x1) / length
        dy = (y2 - y1) / length
        curr_len = 0
        drawing = True

        while curr_len < length:
            step = dash_length if drawing else space_length
            if curr_len + step > length:
                step = length - curr_len

            curr_x2 = x1 + dx * (curr_len + step)
            curr_y2 = y1 + dy * (curr_len + step)

            if drawing:
                self.line(x1 + dx * curr_len, y1 + dy * curr_len, curr_x2, curr_y2)

            curr_len += step
            drawing = not drawing

    @staticmethod
    def format_val(val):
        if val is None or val == "":
            return ""
        try:
            v = float(str(val).replace(',', '.'))
            if v.is_integer() and v != 0:
                return f"{int(v)}"
            return f"{v:.1f}".replace('.', ',')
        except ValueError:
            return str(val)

    @staticmethod
    def format_int(val):
        if val is None or val == "":
            return ""
        try:
            v = float(str(val).replace(',', '.'))
            return f"{int(round(v))}"
        except ValueError:
            return str(val)

    @staticmethod
    def safe_float(val):
        if val is None or val == "": return 0.0
        try:
            return float(str(val).replace(',', '.'))
        except:
            return 0.0

    def header(self):
        self.set_xy(10, 11)
        self.set_font("Arial", "B", 12)
        self.cell(0, 8, "Cenová a materiálová kalkulace nátěrových hmot", border=0, align="L")

        try:
            self.image("img/corro-pdf.png", x=125, y=6, w=45.4)
            self.image("img/corrocoat-pdf.jpg", x=201, y=8.5, h=5.8)
            self.image("img/hempel-pdf.png", x=260, y=7, h=7.0)
        except Exception:
            pass

    def draw_template_grid(self, header_data):
        start_y = 24
        line_height = 5

        self.set_xy(10, start_y)
        labels_keys = [
            ("Dokument č.:", "doc_no"),
            ("Projekt:", "project"),
            ("Provozní teplota:", "temp"),
            ("Korozní zatížení:", "corrosion"),
            ("Podkladový materiál:", "substrate")
        ]

        for label, key in labels_keys:
            self.set_font("Arial", "B", 9)
            self.cell(35, line_height, label, border=0)
            self.set_font("Arial", "", 9)
            self.cell(50, line_height, header_data.get(key, ""), border=0, new_x="LMARGIN", new_y="NEXT")

        self.set_xy(125, start_y)
        self.set_font("Arial", "B", 9)
        self.cell(80, line_height, "CORROTECH OSTRAVA s.r.o.", border=0, new_x="LMARGIN", new_y="NEXT")
        self.set_x(125)
        self.set_font("Arial", "", 9)
        self.cell(80, line_height, "Frýdecká 687/406, 719 00 Ostrava", border=0, new_x="LMARGIN", new_y="NEXT")
        self.set_x(125)
        self.cell(80, line_height, "Tel./fax: +420 734 253 950", border=0, new_x="LMARGIN", new_y="NEXT")
        self.set_x(125)
        self.cell(80, line_height, "E-mail: ostrava@corrotech.com", border=0, new_x="LMARGIN", new_y="NEXT")

        self.set_xy(215, start_y)
        self.set_font("Arial", "B", 9)
        self.cell(80, line_height, "Poptávající / Aplikační firma:", border=0, new_x="LMARGIN", new_y="NEXT")
        self.set_x(215)
        self.set_font("Arial", "", 9)

        # Zpracování dynamického víceřádkového textu firmy
        client_start_y = self.get_y()
        self.multi_cell(80, line_height, header_data.get("client_company", ""), align="L")
        client_end_y = self.get_y()

        # Nalezení spodní hrany (z leva vs zprava)
        current_y = max(start_y + len(labels_keys) * line_height, client_end_y) + 2
        self.set_xy(10, current_y)

        self.set_font("Arial", "B", 9)
        self.cell(35, line_height, "Příprava povrchu:", border=0)
        self.set_font("Arial", "", 9)

        orig_l_margin = self.l_margin
        self.set_left_margin(45)
        self.set_y(current_y + 0.5)

        prep_texts = header_data.get("prep_texts", [])
        for pt in prep_texts:
            if pt.strip():
                self.multi_cell(0, 4, f"-  {pt.strip()}", align="L")
                self.ln(1)

        self.set_left_margin(orig_l_margin)

    def draw_table(self, products_data, main_loss=50, celkova_plocha=1.0, sys_type="", pozn=""):
        self.main_loss = main_loss
        self.set_y(self.get_y() + 4)

        self.set_font("Arial", "B", 9)
        self.cell(15, 5, "Plocha:", border=0)
        self.set_font("Arial", "", 9)
        self.cell(25, 5, f"{self.format_val(celkova_plocha)} m²", border=0)
        self.set_font("Arial", "B", 9)
        self.cell(40, 5, "Typ nátěrového systému:", border=0)
        self.set_font("Arial", "", 9)
        self.cell(40, 5, sys_type, border=0, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

        col_widths = [21, 63.5, 10, 22.5, 10, 9, 9, 11, 11, 12, 17, 9, 9, 11, 11, 12, 12, 17]
        table_width = sum(col_widths)

        self.set_font("Arial", "B", 8)
        self.cell(sum(col_widths[0:8]), 5, pozn, border=1, align="L")

        self.set_fill_color(0, 199, 222)
        self.set_text_color(255, 255, 255)
        self.cell(sum(col_widths[8:11]), 5, "0 % aplikační ztráty", border=1, align="C", fill=True)

        self.set_text_color(0, 0, 0)
        self.cell(sum(col_widths[11:15]), 5, "", border=0)

        self.set_fill_color(255, 0, 0)
        self.set_text_color(255, 255, 255)
        self.cell(sum(col_widths[15:18]), 5, f"{main_loss} % aplikační ztráty", border=1, align="C", fill=True,
                  new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

        headers = [
            ("Typ nátěru", ""), ("Nátěrová hmota / Ředidlo", ""), ("Číslo", "odstínu"), ("Odstín", ""),
            ("Tloušťka", "(DFT)"), ("Sušina", ""), ("% z celk.", "plochy"), ("Teoretická", "vydatnost"),
            ("Teoretická", "spotřeba"), ("Cena", "za m²"), ("Cena", "celkem"), ("Aplikační", "ztráty"),
            ("Ředění", ""), ("Praktická", "vydatnost"), ("Praktická", "spotřeba"), ("Cena", "za Litr"),
            ("Cena", "za m²"), ("Cena", "celkem")
        ]
        self.set_font("Arial", "B", 7)
        current_x = self.get_x()
        current_y = self.get_y()
        row2_height = 17.5

        for i, (line1, line2) in enumerate(headers):
            fill = False
            self.set_text_color(0, 0, 0)
            if i in [9, 10]:
                self.set_fill_color(0, 199, 222)
                self.set_text_color(255, 255, 255)
                fill = True
            elif i in [16, 17]:
                self.set_fill_color(255, 0, 0)
                self.set_text_color(255, 255, 255)
                fill = True
            self.rect(current_x, current_y, col_widths[i], row2_height, style="DF" if fill else "D")

            if i >= 2:
                center_offset = (col_widths[i] / 2) + 1
                if line2:
                    with self.rotation(90, current_x + center_offset - 1.5, current_y + row2_height - 1.5):
                        self.text(current_x + center_offset - 1.5, current_y + row2_height - 1.5, line1)
                    with self.rotation(90, current_x + center_offset + 1.5, current_y + row2_height - 1.5):
                        self.text(current_x + center_offset + 1.5, current_y + row2_height - 1.5, line2)
                else:
                    with self.rotation(90, current_x + center_offset, current_y + row2_height - 1.5):
                        self.text(current_x + center_offset, current_y + row2_height - 1.5, line1)
            else:
                self.set_xy(current_x, current_y + 4.5)
                self.multi_cell(col_widths[i], 4, line1, align="L" if i == 1 else "C", border=0)

            current_x += col_widths[i]
            self.set_xy(current_x, current_y)
        self.set_xy(self.l_margin, current_y + row2_height)

        units = ["", "", "", "", "(μm)", "(obj.%)", "(%)", "(m²/l)", "(L)", "(Kč)", "(Kč)", "(%)", "(%)", "(m²)", "(L)",
                 "(Kč)", "(Kč)", "(Kč)"]
        self.set_font("Arial", "", 6)
        current_x = self.get_x()
        current_y = self.get_y()
        for i, text in enumerate(units):
            fill = False
            self.set_text_color(0, 0, 0)
            if i in [9, 10]:
                self.set_fill_color(0, 199, 222)
                self.set_text_color(255, 255, 255)
                fill = True
            elif i in [16, 17]:
                self.set_fill_color(255, 0, 0)
                self.set_text_color(255, 255, 255)
                fill = True
            self.rect(current_x, current_y, col_widths[i], 5, style="DF" if fill else "D")
            self.set_xy(current_x, current_y)
            self.cell(col_widths[i], 5, text, border=0, align="C", fill=False)
            self.set_draw_color(0, 199, 222) if i in [9, 10] else self.set_draw_color(255, 0, 0) if i in [16,
                                                                                                          17] else self.set_draw_color(
                255, 255, 255)
            self.line(current_x + 0.1, current_y, current_x + col_widths[i] - 0.1, current_y)
            self.set_draw_color(0, 0, 0)
            current_x += col_widths[i]
        self.ln(5)
        self.set_text_color(0, 0, 0)

        sum_teor_cena_m2 = 0.0
        sum_teor_cena = 0.0
        sum_prak_cena_m2 = 0.0
        sum_prak_cena = 0.0
        sum_dft = 0.0

        for i in range(0, len(products_data), 2):
            main_row = products_data[i]
            thinner_row = products_data[i + 1] if i + 1 < len(products_data) else {}

            current_y = self.get_y()
            current_x = self.l_margin

            m_dft = self.safe_float(main_row.get("dft"))
            m_susina = self.safe_float(main_row.get("susina"))
            m_plocha_proc = self.safe_float(main_row.get("plocha"))
            m_real_plocha = celkova_plocha * (m_plocha_proc / 100.0)
            m_c_l = self.safe_float(main_row.get("c_l"))

            m_ztraty = float(self.main_loss)

            t_vyd = (m_susina * 10) / m_dft if m_dft > 0 else 0
            t_spot = m_real_plocha / t_vyd if t_vyd > 0 else 0
            c_m2_t = m_c_l / t_vyd if t_vyd > 0 else 0
            c_celk_t = c_m2_t * m_real_plocha

            p_vyd = (1 - m_ztraty / 100) * t_vyd
            p_spot = m_real_plocha / p_vyd if p_vyd > 0 else 0
            c_m2_p = m_c_l / p_vyd if p_vyd > 0 else 0
            c_celk_p = c_m2_p * m_real_plocha

            main_vals = [
                str(main_row.get("typ", "")), str(main_row.get("hmota", "")), str(main_row.get("cislo", "")),
                str(main_row.get("odstin", "")), self.format_val(m_dft), self.format_val(m_susina),
                self.format_val(m_plocha_proc), self.format_val(t_vyd) if t_vyd else "",
                self.format_val(t_spot) if t_spot else "",
                self.format_val(c_m2_t) if c_m2_t else "", self.format_int(c_celk_t) if c_celk_t else "",
                self.format_val(self.main_loss),  # Zde se tiskne globální ztráta
                self.format_val(main_row.get("redeni", "")), self.format_val(p_vyd) if p_vyd else "",
                self.format_val(p_spot) if p_spot else "", self.format_val(m_c_l),
                self.format_val(c_m2_p) if c_m2_p else "",
                self.format_int(c_celk_p) if c_celk_p else ""
            ]

            red_val = thinner_row.get("redeni")
            t_redeni = 5.0 if red_val in [None, ""] else self.safe_float(red_val)
            t_plocha_proc = m_plocha_proc

            t_t_spot = (m_real_plocha / t_vyd) * (t_redeni / 100.0) if t_vyd > 0 else 0.0
            t_p_spot = p_spot * (t_redeni / 100.0)

            t_c_l = self.safe_float(thinner_row.get("c_l"))
            t_c_m2_t = (t_t_spot * t_c_l) / m_real_plocha if m_real_plocha > 0 else 0.0
            t_c_celk_t = t_t_spot * t_c_l

            t_c_m2_p = (t_p_spot * t_c_l) / m_real_plocha if m_real_plocha > 0 else 0.0
            t_c_celk_p = t_p_spot * t_c_l

            thin_vals = [
                "", str(thinner_row.get("hmota", "")), "", "", "", "",
                self.format_val(t_plocha_proc) if t_plocha_proc else "", "",
                self.format_val(t_t_spot) if t_t_spot else "", self.format_val(t_c_m2_t) if t_c_m2_t else "",
                self.format_int(t_c_celk_t) if t_c_celk_t else "",
                "", self.format_val(t_redeni) if t_redeni else "", "", self.format_val(t_p_spot) if t_p_spot else "",
                self.format_val(t_c_l) if t_c_l else "",
                self.format_val(t_c_m2_p) if t_c_m2_p else "", self.format_int(t_c_celk_p) if t_c_celk_p else ""
            ]

            for col_idx in range(len(col_widths)):
                fill = False
                self.set_text_color(0, 0, 0)
                if col_idx in [9, 10]:
                    self.set_fill_color(0, 199, 222)
                    self.set_text_color(255, 255, 255)
                    fill = True
                elif col_idx in [16, 17]:
                    self.set_fill_color(255, 0, 0)
                    self.set_text_color(255, 255, 255)
                    fill = True
                elif col_idx in [0, 1, 4]:
                    self.set_fill_color(235, 235, 235)
                    fill = True
                self.rect(current_x, current_y, col_widths[col_idx], 10, style="DF" if fill else "D")
                current_x += col_widths[col_idx]

            self.set_font("Arial", "B", 7)
            self.set_xy(self.l_margin, current_y)
            for col_idx, val in enumerate(main_vals):
                align = "L" if col_idx == 1 else "C"
                self.set_text_color(255, 255, 255) if col_idx in [9, 10, 16, 17] else self.set_text_color(0, 0, 0)

                if col_idx == 1:
                    orig_fs = 7
                    fs = orig_fs
                    self.set_font("Arial", "B", fs)
                    while self.get_string_width(val) > (col_widths[col_idx] - 2) and fs > 4:
                        fs -= 0.5
                        self.set_font("Arial", "B", fs)
                    self.cell(col_widths[col_idx], 5, val, border=0, align=align)
                    self.set_font("Arial", "B", orig_fs)
                else:
                    self.cell(col_widths[col_idx], 5, val, border=0, align=align)

            self.set_draw_color(150, 150, 150)
            self.dashed_line(self.l_margin, current_y + 5, self.l_margin + table_width, current_y + 5, dash_length= int(0.5),
                             space_length=1)
            self.set_draw_color(0, 0, 0)

            self.set_font("Arial", "", 7)
            self.set_xy(self.l_margin, current_y + 5)
            for col_idx, val in enumerate(thin_vals):
                align = "L" if col_idx == 1 else "C"
                self.set_text_color(255, 255, 255) if col_idx in [9, 10, 16, 17] else self.set_text_color(0, 0, 0)

                if col_idx == 1:
                    orig_fs = 7
                    fs = orig_fs
                    self.set_font("Arial", "", fs)
                    while self.get_string_width(val) > (col_widths[col_idx] - 2) and fs > 4:
                        fs -= 0.5
                        self.set_font("Arial", "", fs)
                    self.cell(col_widths[col_idx], 5, val, border=0, align=align)
                    self.set_font("Arial", "", orig_fs)
                else:
                    self.cell(col_widths[col_idx], 5, val, border=0, align=align)
            self.ln(5)

            sum_dft += m_dft
            sum_teor_cena_m2 += c_m2_t + t_c_m2_t
            sum_teor_cena += c_celk_t + t_c_celk_t
            sum_prak_cena_m2 += c_m2_p + t_c_m2_p
            sum_prak_cena += c_celk_p + t_c_celk_p

        self.set_text_color(0, 0, 0)
        self.set_font("Arial", "B", 7)
        self.cell(sum(col_widths[:4]), 5, "Celkem", border=1, align="L")
        self.cell(col_widths[4], 5, self.format_val(sum_dft), border=1, align="C")
        self.cell(sum(col_widths[5:9]), 5, "", border=1)

        self.set_fill_color(0, 199, 222)
        self.set_text_color(255, 255, 255)
        self.cell(col_widths[9], 5, self.format_val(sum_teor_cena_m2), border=1, align="C", fill=True)
        self.cell(col_widths[10], 5, self.format_int(sum_teor_cena), border=1, align="C", fill=True)

        self.set_text_color(0, 0, 0)
        self.cell(sum(col_widths[11:16]), 5, "", border=1)

        self.set_fill_color(255, 0, 0)
        self.set_text_color(255, 255, 255)
        self.cell(col_widths[16], 5, self.format_val(sum_prak_cena_m2), border=1, align="C", fill=True)
        self.cell(col_widths[17], 5, self.format_int(sum_prak_cena), border=1, align="C", fill=True)
        self.ln()

        self.sum_teor_cena_m2 = sum_teor_cena_m2
        self.sum_teor_cena = sum_teor_cena

    def footer(self):
        self.set_y(-35)
        y_start = self.get_y()

        losses = [20, 30, 40, 50, 60, 70]
        alt_losses = [l for l in losses if l != getattr(self, 'main_loss', 50)]
        label_w = 20
        val_w = 17
        mini_table_w = label_w + (len(alt_losses) * val_w)
        mini_table_x = self.l_margin + 277 - mini_table_w

        disclaimer_lines = [
            "Všechny ceny jsou uvedeny bez DPH. Ceny výrobků jsou kalkulovány na základě kurzového přepočtu.",
            "Proto v případě jeho výrazného pohybu si nabízející vyhrazuje právo na provedení cenové změny.",
            "Podrobné údaje o výrobcích, přípravě povrchu, aplikaci, intervalech přetíratelnosti atd. viz příslušné Údajové listy výrobků."
        ]

        self.set_font("Arial", "", 8)
        self.set_text_color(0, 0, 0)
        self.set_xy(self.l_margin, y_start)

        for line in disclaimer_lines:
            self.cell(mini_table_x - self.l_margin - 5, 4, line, align="L")
            self.set_xy(self.l_margin, self.get_y() + 4)

        self.set_xy(mini_table_x, y_start)

        self.set_font("Arial", "B", 6)
        self.set_fill_color(255, 0, 0)
        self.set_text_color(255, 255, 255)
        self.cell(label_w, 4, "Apl. ztráta:", border=1, align="L", fill=True)
        for loss in alt_losses:
            self.cell(val_w, 4, f"{loss} %", border=1, align="C", fill=True)
        self.ln()

        self.set_x(mini_table_x)
        self.set_text_color(0, 0, 0)
        self.set_fill_color(255, 255, 255)
        self.set_font("Arial", "B", 6)
        self.cell(label_w, 4, "Cena / m²:", border=1, align="L", fill=True)
        self.set_font("Arial", "", 6)
        for loss in alt_losses:
            factor = 1.0 / (1.0 - loss / 100.0)
            self.cell(val_w, 4, self.format_val(self.sum_teor_cena_m2 * factor), border=1, align="C", fill=True)
        self.ln()

        self.set_x(mini_table_x)
        self.set_font("Arial", "B", 6)
        self.cell(label_w, 4, "Cena celkem:", border=1, align="L", fill=True)
        self.set_font("Arial", "", 6)
        for loss in alt_losses:
            factor = 1.0 / (1.0 - loss / 100.0)
            self.cell(val_w, 4, self.format_int(self.sum_teor_cena * factor), border=1, align="C", fill=True)

        self.set_y(y_start + 15)
        self.set_font("Arial", "B", 8)
        self.set_text_color(0, 0, 0)
        today_str = datetime.date.today().strftime("%d.%m.%Y")

        u_name = self.user_info.get("name", "Neznámý")
        u_phone = str(self.user_info.get("phone", ""))
        if u_phone.strip().lower() in ["none", "nan", ""]:
            u_phone = "+420 734 253 950"
        u_email = self.user_info.get("email", "corrotech@corrotech.com")

        footer_col1 = f"Dne: {today_str}        Zpracoval: {u_name}        Tel.: {u_phone}        E-mail: {u_email}"
        self.cell(180, 5, footer_col1, align="L")

        self.cell(0, 5, f"Platnost kalkulace do: {self.validity_date}        Počet stran: {self.page_no()}", align="R",
                  new_x="LMARGIN", new_y="NEXT")

        self.line(self.l_margin, self.get_y(), self.l_margin + 277, self.get_y())
        self.ln(1)

        y_pos = self.get_y()
        self.set_font("Arial", "", 8)
        company_info = "CORROTECH OSTRAVA s.r.o.  |  Frýdecká 687/406, 719 00 Ostrava - Kunčice  |  +420 734 253 950  |  ostrava@corrotech.com  |  www.corrotech.cz"
        self.set_xy(10, y_pos + 1)
        self.cell(180, 5, company_info, align="L")

        try:
            self.image("img/ak-pdf.jpg", x=225, y=y_pos, h=7)
        except Exception:
            pass
        self.set_xy(240, y_pos + 1)
        self.cell(50, 5, "Člen asociace korozních inženýrů", align="L")