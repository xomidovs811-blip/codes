r"""
One-time fix for "Скидки отчёт 2026-10.xlsx" after the "Время Записи" column was
added to UPLOADS (all UPLOADS columns moved one place to the right).

It:
  * makes a backup copy in  backup\  next to this script
  * points the report formulas at the new UPLOADS columns
  * adds the booking-time check for МРТ / МСКТ (shown in «Замечания» and Telegram)
  * adds the «Время записи» column to «Замечания»
  * rebuilds the «Справочник» sheet (cleaner layout + «Время записи» rules table)
Power Query, the chart and comments are kept: only the sheet XML is edited.

Run (Excel closed, nobody has the file open):
    python fix_workbook.py
    python fix_workbook.py "\\server\path\Скидки отчёт 2026-10.xlsx"
Then run refresh_report.py - Excel recalculates and saves the correct numbers.
"""
import datetime as dt
import html
import os
import re
import shutil
import sys
import tempfile
import zipfile
from xml.sax.saxutils import escape

DEFAULT_FILE = r"\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт\Скидки отчёт 2026-10.xlsx"
HERE = os.path.dirname(os.path.abspath(__file__))

target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
if not os.path.exists(target):
    sys.exit(f"File not found: {target}")
lock = os.path.join(os.path.dirname(target), "~$" + os.path.basename(target))
if os.path.exists(lock):
    sys.exit("The file is open in Excel (lock file exists). Close it everywhere and run again.")

D = tempfile.mkdtemp(prefix="skidki_fix_")
with zipfile.ZipFile(target) as z:
    z.extractall(D)
X = lambda p: os.path.join(D, p)
def rd(p):
    with open(X(p), encoding="utf-8") as f:
        return f.read()
def wr(p, s):
    with open(X(p), "w", encoding="utf-8") as f:
        f.write(s)

def sheet_files():
    wbx, rels = rd("xl/workbook.xml"), rd("xl/_rels/workbook.xml.rels")
    target_of = {}
    for m in re.finditer(r"<Relationship [^>]*>", rels):
        i, t = re.search(r'Id="([^"]+)"', m.group(0)), re.search(r'Target="([^"]+)"', m.group(0))
        target_of[i.group(1)] = t.group(1).lstrip("/").replace("xl/", "", 1)
    return {m.group(1): "xl/" + target_of[m.group(2)]
            for m in re.finditer(r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wbx)}
SHEET = sheet_files()

def read_cells(path):
    """Values of plain (non-formula) cells: {"A6": "text" | number}."""
    ss = []
    if os.path.exists(X("xl/sharedStrings.xml")):
        for si in re.findall(r"<si>(.*?)</si>", rd("xl/sharedStrings.xml"), re.S):
            ss.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
    out = {}
    for m in re.finditer(r'<c r="([A-Z]+\d+)"([^>]*?)(?<!/)>(.*?)</c>', rd(path), re.S):
        ref, attrs, body = m.groups()
        t = re.search(r' t="(\w+)"', attrs)
        t = t.group(1) if t else "n"
        if t == "inlineStr":
            out[ref] = html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", body, re.S)))
            continue
        v = re.search(r"<v>(.*?)</v>", body, re.S)
        if v is None:
            continue
        v = v.group(1)
        out[ref] = ss[int(v)] if t == "s" else html.unescape(v) if t == "str" else float(v) if "." in v or "E" in v else int(v)
    return out

# ---------------------------------------------------------------- safety checks
s7_now = rd(SHEET["Служебный"])
if "flTime" in s7_now:
    sys.exit("This file is already fixed - nothing to do.")
if "Время Записи" not in rd("xl/tables/table1.xml"):
    sys.exit("UPLOADS has no «Время Записи» column - this fix is not for this file.")
if "INDEX(UPLOADS!$C:$C,ROW())&amp;\"\"=\"\"" not in s7_now:
    sys.exit("Unexpected formulas on the «Служебный» sheet - not changing anything.")

def col2n(c):
    n = 0
    for ch in c: n = n * 26 + ord(ch) - 64
    return n

def cell(ref, formula=None, value=None, s=None, text=None, num=None):
    a = f'<c r="{ref}"' + (f' s="{s}"' if s is not None else "")
    if formula is not None:
        return a + f' t="str"><f>{escape(formula)}</f></c>' if text else a + f'><f>{escape(formula)}</f></c>'
    if text is not None:
        return a + f' t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'
    if num is not None:
        return a + f'><v>{num}</v></c>'
    return a + "/>"

def put_cell(row_xml, ref, new_cell):
    """Insert/replace a cell in a <row> keeping column order."""
    col = re.match(r"[A-Z]+", ref).group(0)
    cells = list(re.finditer(r'<c r="([A-Z]+)\d+"[^>]*?(?:/>|>.*?</c>)', row_xml, re.S))
    for m in cells:
        if m.group(1) == col:
            return row_xml[:m.start()] + new_cell + row_xml[m.end():]
    for m in cells:
        if col2n(m.group(1)) > col2n(col):
            return row_xml[:m.start()] + new_cell + row_xml[m.start():]
    i = row_xml.rindex("</row>")
    return row_xml[:i] + new_cell + row_xml[i:]

def edit_rows(sheet_xml, fn):
    """fn(row_number, row_xml) -> row_xml"""
    def rep(m):
        return fn(int(m.group(1)), m.group(0))
    return re.sub(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', rep, sheet_xml, flags=re.S)

def set_formula(row_xml, ref, formula, text=False):
    m = re.search(rf'<c r="{ref}"( s="\d+")?[^>]*?(?:/>|>.*?</c>)', row_xml, re.S)
    s = m.group(1) or ""
    new = f'<c r="{ref}"{s}' + (' t="str"' if text else "") + f"><f>{escape(formula)}</f></c>"
    return row_xml[:m.start()] + new + row_xml[m.end():]

# ---------------------------------------------------------------- 1. UPLOADS columns shifted by one
SHIFT = {c: chr(ord(c) + 1) for c in "BCDEFGHIJKL"}
def remap(xml):
    return re.sub(r"UPLOADS!\$([B-L]):\$\1\b", lambda m: f"UPLOADS!${SHIFT[m.group(1)]}:${SHIFT[m.group(1)]}", xml)

# ---------------------------------------------------------------- 2. styles
st = rd("xl/styles.xml")
fills = re.search(r"<fills count=\"(\d+)\">", st)
nfill = int(fills.group(1))
st = st.replace(fills.group(0), f'<fills count="{nfill + 1}">', 1)
st = st.replace("</fills>", '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill></fills>', 1)
LY = nfill  # light yellow fill id
xfs_m = re.search(r'<cellXfs count="(\d+)">', st)
base = int(xfs_m.group(1))
new_xfs = [
    # 0 input text, left
    f'<xf numFmtId="0" fontId="8" fillId="{LY}" borderId="12" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>',
    # 1 input text, centred
    f'<xf numFmtId="49" fontId="8" fillId="{LY}" borderId="12" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>',
    # 2 input percent, centred
    f'<xf numFmtId="9" fontId="8" fillId="{LY}" borderId="12" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>',
    # 3 input time h:mm, centred
    f'<xf numFmtId="20" fontId="8" fillId="{LY}" borderId="12" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>',
    # 4 input text, wrapped
    f'<xf numFmtId="0" fontId="8" fillId="{LY}" borderId="12" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>',
    # 5 read-only text (from registry), grey font
    '<xf numFmtId="0" fontId="8" fillId="0" borderId="12" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>',
    # 6 plain note text, wrapped
    '<xf numFmtId="0" fontId="8" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>',
    # 7 time in Замечания table (h:mm)
    '<xf numFmtId="20" fontId="8" fillId="0" borderId="13" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>',
]
st = st.replace(xfs_m.group(0), f'<cellXfs count="{base + len(new_xfs)}">', 1)
i = st.index("</cellXfs>")
st = st[:i] + "".join(new_xfs) + st[i:]
wr("xl/styles.xml", st)
S_IN, S_IN_C, S_IN_PCT, S_IN_TIME, S_IN_WRAP, S_RO, S_NOTE, S_TIME = range(base, base + 8)
S_TITLE, S_SUB, S_SECTION, S_HEAD = 44, 30, 56, 34

# ---------------------------------------------------------------- 3. Справочник (sheet6) rebuilt
sp = read_cells(SHEET["Справочник"])
kinds = [tuple(sp.get(f"{c}{r}") for c in "ABCDEFGH") for r in range(6, 106)]
groups = [tuple(sp.get(f"{c}{r}") for c in "JKLM") for r in range(6, 14)]

MRT = "МРТ 10% - будни и воскресенье"
MSKT = "МСКТ 10% - предварительный запись (будни и воскр)"
fix_short = {MRT: "МРТ 10% (ночь 21–07, вс)", MSKT: "МСКТ 10% (воскресенье)"}

rows = {}
def add(r, c): rows.setdefault(r, []).append(c)

add(1, cell("A1", text="Справочник скидок", s=S_TITLE))
add(2, cell("A2", text="Заполняются только жёлтые ячейки. Группа, основание и примечание приходят из реестра скидок (Лист1).", s=S_SUB))
add(4, cell("A4", text="Виды скидок", s=S_SECTION))
add(4, cell("J4", text="Группы", s=S_SECTION))
add(4, cell("O4", text="Пояснения", s=S_SECTION))
for c, h in zip("ABCDEFGH", ["Вид скидки (как в 1С)", "Группа", "Название в отчёте", "Скидка", "Нельзя в дни", "Нужен комментарий", "Основание", "Примечание"]):
    add(5, cell(f"{c}5", text=h, s=S_HEAD))
for c, h in zip("JKLM", ["Группа", "Порядок", "Значок", "В Telegram"]):
    add(5, cell(f"{c}5", text=h, s=S_HEAD))

LAST_INPUT_ROW = 40  # spare yellow rows for new discount types
for i, (a, b, c, d, e, f, g, h) in enumerate(kinds):
    r = 6 + i
    if r > LAST_INPUT_ROW and not a:
        continue
    if a in fix_short:
        c, e = fix_short[a], None  # day/time rule now lives in the "Время записи" table
    add(r, cell(f"A{r}", text=a, s=S_IN) if a else cell(f"A{r}", s=S_IN))
    add(r, cell(f"B{r}", text=b, s=S_RO) if b else cell(f"B{r}", s=S_RO))
    add(r, cell(f"C{r}", text=c, s=S_IN) if c else cell(f"C{r}", s=S_IN))
    add(r, cell(f"D{r}", num=d, s=S_IN_PCT) if isinstance(d, (int, float)) else cell(f"D{r}", s=S_IN_PCT))
    add(r, cell(f"E{r}", text=str(e), s=S_IN_C) if e not in (None, "") else cell(f"E{r}", s=S_IN_C))
    add(r, cell(f"F{r}", text=f, s=S_IN_C) if f else cell(f"F{r}", s=S_IN_C))
    add(r, cell(f"G{r}", text=g, s=S_RO) if g else cell(f"G{r}", s=S_RO))
    add(r, cell(f"H{r}", text=h, s=S_RO) if h else cell(f"H{r}", s=S_RO))

for i, (j, k, l, m) in enumerate(groups):
    r = 6 + i
    add(r, cell(f"J{r}", text=j, s=S_IN) if j else cell(f"J{r}", s=S_IN))
    add(r, cell(f"K{r}", num=k, s=S_IN_C) if k is not None else cell(f"K{r}", s=S_IN_C))
    add(r, cell(f"L{r}", text=l, s=S_IN_C) if l else cell(f"L{r}", s=S_IN_C))
    add(r, cell(f"M{r}", text=m, s=S_IN_C) if m else cell(f"M{r}", s=S_IN_C))

# time-of-booking rules: J16:M27
add(16, cell("J16", text="Время записи", s=S_SECTION))
for c, h in zip("JKLM", ["Вид скидки", "Весь день", "С", "До"]):
    add(17, cell(f"{c}17", text=h, s=S_HEAD))
time_rules = [(MRT, "7", 21 / 24, 7 / 24), (MSKT, "7", None, None)]
for i in range(10):
    r = 18 + i
    name, day, frm, to = time_rules[i] if i < len(time_rules) else (None, None, None, None)
    add(r, cell(f"J{r}", text=name, s=S_IN) if name else cell(f"J{r}", s=S_IN))
    add(r, cell(f"K{r}", text=day, s=S_IN_C) if day else cell(f"K{r}", s=S_IN_C))
    add(r, cell(f"L{r}", num=frm, s=S_IN_TIME) if frm is not None else cell(f"L{r}", s=S_IN_TIME))
    add(r, cell(f"M{r}", num=to, s=S_IN_TIME) if to is not None else cell(f"M{r}", s=S_IN_TIME))
for r, t in ((28, "Приказ с 01.06.2026: МРТ — пн–сб с 21:00 до 07:00, в вс весь день; МСКТ — только в вс."),
             (29, "«Весь день» — дни, когда время записи не важно (1 пн … 7 вс)."),
             (30, "Если «С» и «До» пустые, в остальные дни скидка не положена.")):
    add(r, cell(f"J{r}", text=t, s=S_SUB))

notes = [
    "Отчёт обновляется каждый день автоматически. Вручную: Данные → Обновить всё, потом дата на листе «Отчёт» (C4).",
    "Новый вид скидки: добавить строку в таблицу слева. Название копировать точно из UPLOADS, столбец «Вид скидки».",
    "Скидка — процент по положению. Если фактическая скидка больше более чем на 1% — замечание. Пусто — не проверяется.",
    "Нельзя в дни — номера дней через запятую: 1 пн, 2 вт, 3 ср, 4 чт, 5 пт, 6 сб, 7 вс.",
    "Нужен комментарий — «Да»: документ без комментария попадёт в замечания.",
    "Время записи — для скидок, которые зависят от часа записи (МРТ, МСКТ). Сверяется со столбцом «Время Записи» в UPLOADS.",
    "Группы — порядок блоков в отчёте и в Telegram. «Кратко» — одна строка на вид скидки.",
    "Группу Power Query берёт из реестра (Лист1). Вида нет в реестре — он попадёт в «Вне реестра» и в замечания.",
]
for i, t in enumerate(notes):
    add(5 + i, cell(f"O{5 + i}", text=t, s=26))

def build_rows():
    out = []
    for r in sorted(rows):
        cs = sorted(rows[r], key=lambda c: col2n(re.match(r'<c r="([A-Z]+)', c).group(1)))
        ht = {1: ' ht="18" customHeight="1"', 5: ' ht="30" customHeight="1"'}.get(r, "")
        out.append(f'<row r="{r}"{ht}>' + "".join(cs) + "</row>")
    return "".join(out)

s6 = rd(SHEET["Справочник"])
s6 = re.sub(r"<sheetData>.*</sheetData>", "<sheetData>" + build_rows() + "</sheetData>", s6, flags=re.S)
s6 = re.sub(r'<dimension ref="[^"]*"/>', '<dimension ref="A1:O105"/>', s6)
s6 = s6.replace('<sheetView workbookViewId="0">', '<sheetView showGridLines="0" workbookViewId="0">', 1)
s6 = re.sub(r'<selection pane="bottomRight"[^>]*/>', '<selection pane="bottomRight" activeCell="A6" sqref="A6"/>', s6)
widths = {1: 66, 2: 33, 3: 40, 4: 9, 5: 12, 6: 13, 7: 25, 8: 35, 9: 3, 10: 50, 11: 10, 12: 9, 13: 12, 14: 3, 15: 115}
s6 = re.sub(r"<cols>.*?</cols>", "<cols>" + "".join(f'<col min="{k}" max="{k}" width="{v}" style="27" customWidth="1"/>' for k, v in widths.items()) + "</cols>", s6, flags=re.S)
s6 = s6.replace("</dataValidations>",
    '<dataValidation type="time" allowBlank="1" showErrorMessage="1" error="Введите время, например 21:00" sqref="L18:M27"><formula1>0</formula1><formula2>0.999988425925926</formula2></dataValidation></dataValidations>')
s6 = s6.replace('<dataValidations count="3">', '<dataValidations count="4">')
wr(SHEET["Справочник"], s6)

# ---------------------------------------------------------------- 4. Служебный (sheet7)
TB = "Справочник!$J$18:$J$27"
def r_formulas(r):
    return {
        "AH": f'IF(Q{r}<>1,0,IF(OR(AP{r}>0,AND(AA{r}<>"",ISNUMBER(SEARCH(WEEKDAY(A{r},2),AA{r})))),1,0))',
        "AP": f'IF(CB{r}=0,0,IF(ISNUMBER(SEARCH(WEEKDAY(A{r},2),INDEX(Справочник!$K$18:$K$27,CB{r})&"")),0,IF(CC{r}="",2,IF(OR(CD{r}="",CE{r}=""),1,IF(IF(CD{r}<=CE{r},AND(CC{r}>=CD{r},CC{r}<=CE{r}),OR(CC{r}>=CD{r},CC{r}<=CE{r})),0,1)))))',
        "CB": f'IF(Q{r}<>1,0,IFERROR(MATCH(E{r},{TB},0),0))',
        "CC": f'IF(CB{r}=0,"",IF(INDEX(UPLOADS!$B:$B,ROW())&""="","",IF(ISNUMBER(INDEX(UPLOADS!$B:$B,ROW())),ROUND(MOD(INDEX(UPLOADS!$B:$B,ROW()),1)*1440,0),IFERROR(ROUND(MOD(TIMEVALUE(INDEX(UPLOADS!$B:$B,ROW())&""),1)*1440,0),""))))',
        "CD": f'IF(CB{r}=0,"",IF(INDEX(Справочник!$L$18:$L$27,CB{r})&""="","",ROUND(MOD(INDEX(Справочник!$L$18:$L$27,CB{r}),1)*1440,0)))',
        "CE": f'IF(CB{r}=0,"",IF(INDEX(Справочник!$M$18:$M$27,CB{r})&""="","",ROUND(MOD(INDEX(Справочник!$M$18:$M$27,CB{r}),1)*1440,0)))',
    }
OLD_AM_PART = 'IF(AH{r}=1,"Запрещённый день недели; ","")'
def new_am_part(r):
    tm = f'INT(CC{r}/60)&":"&RIGHT("0"&MOD(CC{r},60),2)'
    wd = f'CHOOSE(WEEKDAY(A{r},2),"пн","вт","ср","чт","пт","сб","вс")'
    return (f'IF(AND(AH{r}=1,AP{r}=0),"Запрещённый день недели; ","")'
            f'&IF(AP{r}=1,"Скидка не положена: запись в "&{tm}&", "&{wd}&"; ","")'
            f'&IF(AP{r}=2,"Не указано время записи; ","")')

s7 = remap(rd(SHEET["Служебный"]))
AM3 = html.unescape(re.search(r'<c r="AM3"[^>]*><f[^>]*>(.*?)</f>', s7, re.S).group(1))
AM_TEMPLATE = re.sub(r"\b([A-Z]{1,2})3\b", r"\1{r}", AM3)
assert OLD_AM_PART in AM_TEMPLATE, AM_TEMPLATE
def fix7(r, row):
    if r == 2:
        for c, h in (("AP", "flTime"), ("CB", "tmIdx"), ("CC", "tmMin"), ("CD", "tmFrom"), ("CE", "tmTo")):
            row = put_cell(row, f"{c}2", cell(f"{c}2", text=h))
        return row
    if r == 90:
        row = put_cell(row, "AQ90", cell("AQ90", text="Текст нарушения дня/времени"))
        return set_formula(row, "AR90", '"вне разрешённого дня/времени"', text=True)
    if 3 <= r <= 5002:
        f = r_formulas(r)
        row = set_formula(row, f"AH{r}", f["AH"])
        am = AM_TEMPLATE.replace("{r}", str(r))
        row = set_formula(row, f"AM{r}", am.replace(OLD_AM_PART.format(r=r), new_am_part(r)), text=True)
        for c in ("AP", "CB", "CC", "CD", "CE"):
            row = put_cell(row, f"{c}{r}", cell(f"{c}{r}", formula=f[c], text=(c in ("CC", "CD", "CE"))))
    return row
s7 = edit_rows(s7, fix7)
s7 = re.sub(r'<dimension ref="A1:[A-Z]+(\d+)"/>', r'<dimension ref="A1:CE\1"/>', s7)
s7 = re.sub(r' spans="\d+:\d+"', "", s7)
wr(SHEET["Служебный"], s7)

# ---------------------------------------------------------------- 5. Замечания (sheet3): remap + "Время записи" column M
s3 = remap(rd(SHEET["Замечания"]))
def fix3(r, row):
    if r == 5:
        return put_cell(row, "M5", cell("M5", text="Время записи", s=S_HEAD))
    if 6 <= r <= 305:
        n = r - 5
        f = f'IF($A{r}="","",IF(INDEX(UPLOADS!$B:$B,(MATCH({n},Служебный!$AO$3:$AO$5002,0)+2))&""="","",INDEX(UPLOADS!$B:$B,(MATCH({n},Служебный!$AO$3:$AO$5002,0)+2))))'
        return put_cell(row, f"M{r}", cell(f"M{r}", formula=f, s=S_TIME))
    return row
s3 = edit_rows(s3, fix3)
s3 = re.sub(r' spans="\d+:\d+"', "", s3)
s3 = s3.replace('<dimension ref="A1:L305"/>', '<dimension ref="A1:M305"/>')
s3 = s3.replace('<col min="12" max="12" width="40" style="27" customWidth="1"/>', '<col min="12" max="12" width="40" style="27" customWidth="1"/><col min="13" max="13" width="12" style="27" customWidth="1"/>')
s3 = s3.replace('<conditionalFormatting sqref="A6:L305">', '<conditionalFormatting sqref="A6:M305">')
wr(SHEET["Замечания"], s3)

# ---------------------------------------------------------------- 6. UPLOADS (sheet5): subtotals G1:J1 -> H1:K1
s5 = rd(SHEET["UPLOADS"])
row1 = re.search(r'<row r="1"[^>]*>.*?</row>', s5, re.S).group(0)
new1 = row1
for a, b in (("J", "K"), ("I", "J"), ("H", "I"), ("G", "H")):
    new1 = new1.replace(f'r="{a}1"', f'r="{b}1"').replace(f"SUBTOTAL(9,{a}3:{a}1048576)", f"SUBTOTAL(9,{b}3:{b}1048576)")
new1 = re.sub(r"<v>[^<]*</v>", "", new1)
s5 = s5.replace(row1, new1)
wr(SHEET["UPLOADS"], s5)

# ---------------------------------------------------------------- 7. full recalc on open, drop calcChain
wbx = rd("xl/workbook.xml")
wbx = re.sub(r"<calcPr([^>]*)/>", lambda m: "<calcPr" + re.sub(r' fullCalcOnLoad="\d"', "", m.group(1)) + ' fullCalcOnLoad="1"/>', wbx)
wr("xl/workbook.xml", wbx)
if os.path.exists(X("xl/calcChain.xml")):
    os.remove(X("xl/calcChain.xml"))
    wr("xl/_rels/workbook.xml.rels", re.sub(r'<Relationship [^>]*calcChain[^>]*/>', "", rd("xl/_rels/workbook.xml.rels")))
    wr("[Content_Types].xml", re.sub(r'<Override [^>]*calcChain[^>]*/>', "", rd("[Content_Types].xml")))


# ---------------------------------------------------------------- write back (with backup)
os.makedirs(os.path.join(HERE, "backup"), exist_ok=True)
backup = os.path.join(HERE, "backup", f"{os.path.splitext(os.path.basename(target))[0]} {dt.datetime.now():%Y%m%d-%H%M%S}.xlsx")
shutil.copy2(target, backup)
tmp = target + ".fixing"
files = []
for root, _, fs in os.walk(D):
    for f in fs:
        files.append(os.path.relpath(os.path.join(root, f), D).replace(os.sep, "/"))
files.sort(key=lambda p: (p != "[Content_Types].xml", not p.startswith("_rels"), p))
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(os.path.join(D, f), f)
os.replace(tmp, target)
shutil.rmtree(D, ignore_errors=True)
print("Backup:", backup)
print("Fixed: ", target)
print("Now run: python refresh_report.py   (Excel recalculates and saves the right numbers)")
