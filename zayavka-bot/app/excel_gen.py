"""
Builds a .xlsx file matching the polished reference template
(Zayavka_sample.xlsx, latest edit): navy/light-blue
palette, header block at rows 1-5 (2-column-wide labels), a table header
directly at row 6 (no gap row), a "НОМЕР ЗАЯВКИ" box split into a label
region (L1:L2) and a plain large-text number region (L3:L5), plain
helper columns N/O/P/Q mirroring Номер/От кого/Объект/Дата onto every row,
negative Остатка highlighted red,
subtotals summed across all three money columns per supplier group, a
single consolidated "СУММА ЗАЯВКИ" row, and an Инспектор/Кассир/
Заявитель/Техданзор/Директор sign-off block with a "Тасдик !!!"
confirmation.

Built programmatically (not by editing a fixed-size copy of the original)
so it works correctly no matter how many item rows there are.
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app.config import PAYMENT_TYPES

# --- palette, straight from the reference file ---
NAVY = "1F4E78"
NAVY_TEXT = "17365D"
LABEL_BG = "EEF5FB"
NUMBER_LABEL_BG = "DCEAF7"
SUBTOTAL_BG = "CFE3F5"
REMAINDER_BG = "EEF5FB"
GREEN_BG = "D9EAD3"
GREEN_TEXT = "274E13"

LABEL_FONT = Font(name="Calibri", size=11, bold=True, color=NAVY_TEXT)
VALUE_FONT = Font(name="Calibri", size=11, bold=True, color=NAVY_TEXT)
NUMBER_LABEL_FONT = Font(name="Calibri", size=16, bold=True, color=NAVY)
NUMBER_VALUE_FONT = Font(name="Calibri", size=24)
TABLE_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
HELPER_HEADER_FONT = Font(name="Calibri", size=11)
ITEM_FONT = Font(name="Calibri", size=11)
HELPER_FONT = Font(name="Calibri", size=11)
SUBTOTAL_FONT = Font(name="Calibri", size=11, bold=True, color=NAVY)
TOTAL_ROW_FONT = Font(name="Calibri", size=12, bold=True, color="FFFFFF")
TOTAL_ROW_GREEN_FONT = Font(name="Calibri", size=12, bold=True, color=GREEN_TEXT)
SIGN_LABEL_FONT = Font(name="Calibri", size=12, bold=True, color=NAVY_TEXT)
SIGN_VALUE_FONT = Font(name="Calibri", size=14, bold=True, color=NAVY)
DIRECTOR_VALUE_FONT = Font(name="Calibri", size=16, bold=True, color=NAVY)
CONFIRM_HEADER_FONT = Font(name="Calibri", size=14, bold=True, color=NAVY_TEXT)
CONFIRM_TEXT_FONT = Font(name="Calibri", size=11)

THIN = Side(style="thin", color="C9D6E3")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
CENTER_NOWRAP = Alignment(horizontal="center", vertical="center")
RIGHT_NOWRAP = Alignment(horizontal="right", vertical="center")
WRAP_MID = Alignment(vertical="center", wrap_text=True)
LEFT_MID = Alignment(horizontal="left", vertical="center")

LABEL_FILL = PatternFill("solid", fgColor=LABEL_BG)
VALUE_FILL = PatternFill("solid", fgColor="FFFFFF")
NUMBER_LABEL_FILL = PatternFill("solid", fgColor=NUMBER_LABEL_BG)
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
SUBTOTAL_FILL = PatternFill("solid", fgColor=SUBTOTAL_BG)
REMAINDER_FILL = PatternFill("solid", fgColor=REMAINDER_BG)
TOTAL_FILL = PatternFill("solid", fgColor=NAVY)
TOTAL_GREEN_FILL = PatternFill("solid", fgColor=GREEN_BG)
NEGATIVE_FILL = PatternFill("solid", bgColor="F4CCCC", fgColor="F4CCCC")

# Verbatim from the original sign-off template - note ҳ (not х) in ҳажм*/ҳисоб*.
CONFIRM_TEXT_1 = (
    "Мен, инспектор сифатида, объектда бажарилган ишларни жойида текширдим, "
    "иш ҳажмларини ўлчадим ва уларнинг тўғри бажарилганлигини тасдиқлайман."
)
CONFIRM_TEXT_2 = (
    "Мен, Прораб сифатида, бажарилган ишлар сифатли, белгиланган меъёрларга "
    "мувофиқ бажарилганлиги, иш ҳажмлари тўғри ҳисобланганлиги ва такрорий "
    "киритилмаганлигини тасдиқлайман."
)

# (field key, header label, column width) - columns A..M (the visible table).
ITEM_COLUMNS = [
    ("row_no", "Т/р", 12.44),
    ("product_name", "Наименование товара", 43),
    ("supplier", "Поставщик", 22),
    ("block", "Блок", 9),
    ("floor", "Этаж", 9.33),
    ("unit", "Ед. изм.", 10),
    ("qty", "Кол-во", 11),
    ("price", "Цена", 14),
    ("total", "Общая сумма", 15),
    ("advance", "Аванс получ-ил", 15.33),
    ("remainder", "Остатка", 15),
    ("work_type", "Выполняемая работа (сметная группа)", 38),
    ("comment", "Комментарии", 22),
]
# Helper columns N/O/P/Q: mirror Номер/От кого/Объект/Дата onto every row
# from the first item row down to the end of the Тасдик block (handy for
# filtering/lookups if this sheet ever gets combined with others). They're
# plain/unstyled and sit outside the print area, but not actually hidden.
HELPER_COLUMNS = [
    ("НОМЕР ЗАЯВКИ", "=$L$3", 14, 17.89),
    ("От кого:", "=$C$3", 15, 17.0),
    ("Название объекта:", "=$C$1", 16, 18.11),
    ("Дата:", "=$C$2", 17, 13.0),
]
HELPER_DATE_COL = 17

HEADER_ROW = 6
FIRST_ITEM_ROW = 7


def _group_by_supplier(items: list) -> list:
    """
    Consecutive items sharing the same (trimmed) Поставщик become one
    group. An item with no supplier (e.g. an "Olingan avans ..." advance
    line, which only fills Наименование/Аванс) isn't a group of its own -
    it continues whatever group came before it, since that's how these
    rows appear in the real workbook (folded into the preceding
    supplier's subtotal).
    """
    groups = []
    for item in items:
        supplier = (item.get("supplier") or "").strip()
        if not supplier and groups:
            groups[-1][1].append(item)
        elif groups and groups[-1][0] == supplier:
            groups[-1][1].append(item)
        else:
            groups.append((supplier, [item]))
    return groups


def build_workbook(zayavka: dict) -> Workbook:
    """
    zayavka: {
      "number": str, "object_name": str, "date": date, "from_whom": str,
      "to_whom": str, "payment_type": str,
      "inspector": str, "cashier": str, "tech_supervisor": str,
      "items": [ {row_no, product_name, supplier, block, floor, unit,
                  qty, price, advance, work_type, comment}, ... ]
    }
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Заявка"
    ws.sheet_view.showGridLines = False

    items = zayavka["items"]
    groups = _group_by_supplier(items)

    # column widths A..M, plus the helper columns N/O/P
    for idx, (_, _label, width) in enumerate(ITEM_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for _label, _formula, col_offset, width in HELPER_COLUMNS:
        ws.column_dimensions[get_column_letter(col_offset)].width = width

    # --- header block (rows 1-5): 2-column-wide label + 9-column value ---
    header_fields = [
        (1, "Название объекта:", zayavka["object_name"], 24),
        (2, "Дата:", zayavka["date"], 22.05),
        (3, "От кого:", zayavka["from_whom"], 22.05),
        (4, "Кому:", zayavka["to_whom"], 22.05),
        (5, "Вид оплаты:", zayavka["payment_type"], 22.05),
    ]
    for row, label, value, height in header_fields:
        ws.row_dimensions[row].height = height
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        a = ws.cell(row=row, column=1, value=label)
        a.font = LABEL_FONT
        a.fill = LABEL_FILL
        a.alignment = LEFT_MID
        a.border = BORDER

        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=11)
        v = ws.cell(row=row, column=3, value=value)
        v.font = VALUE_FONT
        v.fill = VALUE_FILL
        v.alignment = CENTER_NOWRAP
        v.border = BORDER
        if row == 2:
            v.number_format = "DD.MM.YYYY"

    # "НОМЕР ЗАЯВКИ": label box (L1:L2) + a separate plain large-text
    # number box (L3:L5) below it - both static text.
    ws.merge_cells("L1:L2")
    label_box = ws["L1"]
    label_box.value = "НОМЕР ЗАЯВКИ"
    label_box.font = NUMBER_LABEL_FONT
    label_box.fill = NUMBER_LABEL_FILL
    label_box.alignment = CENTER
    label_box.border = BORDER

    ws.merge_cells("L3:L5")
    number_box = ws["L3"]
    number_box.value = zayavka["number"]
    number_box.font = NUMBER_VALUE_FONT
    number_box.alignment = CENTER_NOWRAP
    number_box.border = BORDER

    # Only Вид оплаты keeps a dropdown, as an inline list (the reference
    # sample has a single sheet, no hidden справочник, and no other dropdowns).
    dv_pay = DataValidation(type="list", formula1='"' + ",".join(PAYMENT_TYPES) + '"', allow_blank=True)
    ws.add_data_validation(dv_pay)
    dv_pay.add(ws["C5"])

    # the merged number/label boxes and the column beside them get the full
    # thin border (every cell of a merged range, so the box draws completely)
    for row in range(1, 6):
        ws.cell(row=row, column=12).border = BORDER
        ws.cell(row=row, column=13).border = BORDER

    # --- table header row (visible A-M + plain N/O/P helper headers) ---
    ws.row_dimensions[HEADER_ROW].height = 37.95
    for idx, (_, label, _w) in enumerate(ITEM_COLUMNS, start=1):
        cell = ws.cell(row=HEADER_ROW, column=idx, value=label)
        cell.font = TABLE_HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER
    for label, _formula, col_offset, _w in HELPER_COLUMNS:
        cell = ws.cell(row=HEADER_ROW, column=col_offset, value=label)
        cell.font = HELPER_HEADER_FONT
        cell.alignment = CENTER_NOWRAP

    # --- item rows, with an "ИТОГО: <supplier>" subtotal row (summed
    # across Общая сумма/Аванс/Остатка) after each consecutive run of
    # same-supplier items; subtotal rows don't get a т/р number. ---
    r = FIRST_ITEM_ROW
    tr_no = 1
    subtotal_rows = []
    for supplier, group_items in groups:
        group_start = r
        for item in group_items:
            product_name = item.get("product_name") or ""
            ws.row_dimensions[r].height = 31.95 if "\n" in product_name else 25.05
            ws.cell(row=r, column=1, value=tr_no).alignment = CENTER_NOWRAP           # A т/р
            ws.cell(row=r, column=2, value=product_name).alignment = WRAP_MID         # B
            ws.cell(row=r, column=3, value=item.get("supplier") or "").alignment = LEFT_MID       # C
            ws.cell(row=r, column=4, value=item.get("block") or "").alignment = CENTER_NOWRAP     # D
            ws.cell(row=r, column=5, value=item.get("floor") or "").alignment = CENTER_NOWRAP     # E
            ws.cell(row=r, column=6, value=item.get("unit") or "").alignment = CENTER_NOWRAP      # F
            ws.cell(row=r, column=7, value=item.get("qty")).alignment = RIGHT_NOWRAP              # G
            price_cell = ws.cell(row=r, column=8, value=item.get("price"))                         # H Цена
            price_cell.alignment = RIGHT_NOWRAP
            price_cell.number_format = "#,##0"
            total_cell = ws.cell(row=r, column=9, value=f"=G{r}*H{r}")                            # I Общая сумма
            total_cell.alignment = RIGHT_NOWRAP
            total_cell.number_format = "#,##0"
            adv_cell = ws.cell(row=r, column=10, value=item.get("advance"))                        # J Аванс
            adv_cell.alignment = RIGHT_NOWRAP
            adv_cell.number_format = "#,##0"
            rem_cell = ws.cell(row=r, column=11, value=f"=I{r}-J{r}")                              # K Остатка
            rem_cell.alignment = RIGHT_NOWRAP
            rem_cell.number_format = "#,##0"
            rem_cell.fill = REMAINDER_FILL
            work_cell = ws.cell(row=r, column=12, value=item.get("work_type") or "")               # L
            work_cell.alignment = WRAP_MID
            ws.cell(row=r, column=13, value=item.get("comment") or "").alignment = WRAP_MID        # M

            for col in range(1, 14):
                ws.cell(row=r, column=col).border = BORDER
                if col != 3:
                    ws.cell(row=r, column=col).font = ITEM_FONT
            r += 1
            tr_no += 1

        group_end = r - 1
        ws.row_dimensions[r].height = 24
        subtotal_label = ws.cell(row=r, column=1, value=f"ИТОГО: {supplier}" if supplier else "ИТОГО:")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
        subtotal_label.alignment = LEFT_MID
        i_sub = ws.cell(row=r, column=9, value=f"=SUM(I{group_start}:I{group_end})")
        j_sub = ws.cell(row=r, column=10, value=f"=SUM(J{group_start}:J{group_end})")
        k_sub = ws.cell(row=r, column=11, value=f"=SUM(K{group_start}:K{group_end})")
        for c in (i_sub, j_sub, k_sub):
            c.alignment = RIGHT_NOWRAP
            c.number_format = "#,##0"
        for col in range(1, 14):
            cell = ws.cell(row=r, column=col)
            cell.fill = SUBTOTAL_FILL
            cell.font = SUBTOTAL_FONT
            cell.border = BORDER
        subtotal_rows.append(r)
        r += 1
        # tr_no does NOT advance here - subtotal rows show no т/р number,
        # so item numbering stays clean and consecutive (1, 2, 3, ...).

    last_row = r - 1

    # --- СУММА ЗАЯВКИ: one consolidated row, summed from the subtotal rows
    # only (summing the full item range too would double-count each item). ---
    sum_row = last_row + 2
    ws.row_dimensions[sum_row].height = 21.6
    ws.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=8)
    sum_label = ws.cell(row=sum_row, column=1, value="СУММА ЗАЯВКИ")
    sum_label.font = TOTAL_ROW_FONT
    sum_label.alignment = LEFT_MID

    i_refs = "+".join(f"I{sr}" for sr in subtotal_rows) or "0"
    j_refs = "+".join(f"J{sr}" for sr in subtotal_rows) or "0"
    k_refs = "+".join(f"K{sr}" for sr in subtotal_rows) or "0"
    i_total = ws.cell(row=sum_row, column=9, value=f"={i_refs}")
    j_total = ws.cell(row=sum_row, column=10, value=f"={j_refs}")
    k_total = ws.cell(row=sum_row, column=11, value=f"={k_refs}")
    for c in (i_total, j_total):
        c.font = TOTAL_ROW_FONT
        c.alignment = RIGHT_NOWRAP
        c.number_format = "#,##0"
    k_total.font = TOTAL_ROW_GREEN_FONT
    k_total.alignment = RIGHT_NOWRAP
    k_total.number_format = "#,##0"
    k_total.fill = TOTAL_GREEN_FILL

    for col in range(1, 14):
        cell = ws.cell(row=sum_row, column=col)
        cell.border = BORDER
        if col != 11:
            cell.fill = TOTAL_FILL

    # --- sign-off section: Инспектор / Кассир / Заявитель / Техданзор / Директор ---
    insp_row = sum_row + 2
    ws.row_dimensions[insp_row].height = 18
    ws.cell(row=insp_row, column=1, value="Инспектор:").font = SIGN_LABEL_FONT
    ws.cell(row=insp_row, column=2, value=zayavka.get("inspector") or "").font = SIGN_VALUE_FONT
    ws.merge_cells(start_row=insp_row, start_column=4, end_row=insp_row, end_column=5)
    ws.cell(row=insp_row, column=4, value="Кассир:").font = SIGN_LABEL_FONT
    ws.cell(row=insp_row, column=4).alignment = CENTER_NOWRAP
    ws.merge_cells(start_row=insp_row, start_column=6, end_row=insp_row, end_column=9)
    ws.cell(row=insp_row, column=6, value=zayavka.get("cashier") or "").font = SIGN_VALUE_FONT

    req_row = insp_row + 3
    ws.row_dimensions[req_row].height = 21
    ws.cell(row=req_row, column=1, value="Заявитель:").font = SIGN_LABEL_FONT
    ws.cell(row=req_row, column=2, value=zayavka["from_whom"]).font = SIGN_VALUE_FONT
    ws.merge_cells(start_row=req_row, start_column=4, end_row=req_row, end_column=5)
    ws.cell(row=req_row, column=4, value="Техданзор:").font = SIGN_LABEL_FONT
    ws.cell(row=req_row, column=4).alignment = CENTER_NOWRAP
    ws.merge_cells(start_row=req_row, start_column=6, end_row=req_row, end_column=9)
    ws.cell(row=req_row, column=6, value=zayavka.get("tech_supervisor") or "").font = SIGN_VALUE_FONT
    ws.cell(row=req_row, column=11, value="Директор:").font = SIGN_LABEL_FONT
    ws.cell(row=req_row, column=12, value=zayavka["to_whom"]).font = DIRECTOR_VALUE_FONT

    # --- Тасдик confirmation block ---
    confirm_row = req_row + 2
    ws.row_dimensions[confirm_row].height = 18
    ws.cell(row=confirm_row, column=1, value="Тасдик !!!").font = CONFIRM_HEADER_FONT
    c1 = ws.cell(row=confirm_row, column=2, value=CONFIRM_TEXT_1)
    c1.font = CONFIRM_TEXT_FONT
    c2 = ws.cell(row=confirm_row + 1, column=2, value=CONFIRM_TEXT_2)
    c2.font = CONFIRM_TEXT_FONT

    # helper columns N-Q on every row down to the end of the Тасдик block
    for row in range(FIRST_ITEM_ROW, confirm_row + 2):
        for _label, formula, col_offset, _w in HELPER_COLUMNS:
            cell = ws.cell(row=row, column=col_offset, value=formula)
            cell.font = HELPER_FONT
            cell.alignment = CENTER_NOWRAP
            if col_offset == HELPER_DATE_COL:
                cell.number_format = "DD.MM.YYYY"

    # a negative Остатка (overpaid / advance exceeds the total) is flagged red
    ws.conditional_formatting.add(
        f"K{FIRST_ITEM_ROW}:K{sum_row}",
        CellIsRule(operator="lessThan", formula=["0"], fill=NEGATIVE_FILL),
    )

    ws.freeze_panes = f"A{FIRST_ITEM_ROW}"

    # print-friendly: landscape, fit to one page wide. The reference file's
    # own print area got left at A1:M29 (cutting off the sign-off block
    # below it) after rows were added below - almost certainly stale from
    # an earlier edit, not intentional, so the full sheet (through the
    # Тасдик block) is used here instead.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:M{confirm_row + 1}"

    return wb


def save_workbook(zayavka: dict, out_dir: str) -> str:
    wb = build_workbook(zayavka)
    safe_number = zayavka["number"].replace("/", "-")
    filename = f"Zayavka-{safe_number}.xlsx"
    path = str(Path(out_dir) / filename)
    wb.save(path)
    return path
