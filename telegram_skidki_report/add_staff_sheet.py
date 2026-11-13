r"""
Copy the «Скидки сотрудникам» sheet (PivotTable) from one month's report into another,
and point the copy at that month's own data (table «База_продаж»).

Default: from «Скидки отчёт 2026-11.xlsx» into «Скидки отчёт 2026-10.xlsx».
    python add_staff_sheet.py
    python add_staff_sheet.py 2026-11 2026-10      (from, to)

Both files must be closed. A backup of the target is saved in backup\ first.
Needs: Windows + Microsoft Excel, pywin32.
"""
import datetime as dt
import os
import shutil
import sys

REPORT_FOLDER = r"\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт"
FILE_BASE_NAME = "Скидки отчёт"
SHEET = "Скидки сотрудникам"
AFTER_SHEET = "Замечания"
TABLE = "База_продаж"
PAGE_FIELD = "Группа скидки"
HERE = os.path.dirname(os.path.abspath(__file__))


def items(collection):
    return [collection.Item(i) for i in range(1, collection.Count + 1)]


def main():
    src_month, dst_month = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("2026-11", "2026-10")
    src = os.path.join(REPORT_FOLDER, f"{FILE_BASE_NAME} {src_month}.xlsx")
    dst = os.path.join(REPORT_FOLDER, f"{FILE_BASE_NAME} {dst_month}.xlsx")
    for p in (src, dst):
        if not os.path.exists(p):
            sys.exit(f"File not found: {p}")
        if os.path.exists(os.path.join(os.path.dirname(p), "~$" + os.path.basename(p))):
            sys.exit(f"File is open in Excel - close it everywhere: {p}")

    os.makedirs(os.path.join(HERE, "backup"), exist_ok=True)
    backup = os.path.join(HERE, "backup", f"{FILE_BASE_NAME} {dst_month} {dt.datetime.now():%Y%m%d-%H%M%S}.xlsx")
    shutil.copy2(dst, backup)
    print("Backup:", backup)

    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb_src = wb_dst = None
    try:
        wb_src = excel.Workbooks.Open(src, UpdateLinks=0, ReadOnly=True)
        wb_dst = excel.Workbooks.Open(dst, UpdateLinks=0, ReadOnly=False)
        if wb_dst.ReadOnly:
            sys.exit(f"{dst} is open by someone - close it and run again")
        if any(ws.Name == SHEET for ws in wb_dst.Worksheets):
            print(f"«{SHEET}» already exists in {os.path.basename(dst)} - nothing to do.")
            return 0

        src_pt = wb_src.Worksheets(SHEET).PivotTables(1)
        visible = [it.Name for it in items(src_pt.PivotFields(PAGE_FIELD).PivotItems()) if it.Visible]
        calc_fields = [(cf.Name, cf.Formula) for cf in items(src_pt.CalculatedFields())]
        data_fields = [(df.Name, df.SourceName, df.Function, df.NumberFormat) for df in items(src_pt.DataFields)]

        # 1. copy the sheet
        wb_src.Worksheets(SHEET).Copy(After=wb_dst.Worksheets(AFTER_SHEET))
        ws = wb_dst.Worksheets(SHEET)
        pt = ws.PivotTables(1)
        print("Sheet copied")

        # 2. point the pivot at this file's own data
        cache = wb_dst.PivotCaches().Create(SourceType=1, SourceData=TABLE)  # 1 = xlDatabase
        pt.ChangePivotCache(cache)
        if "[" in str(pt.SourceData):
            raise RuntimeError(f"Pivot still points to another file: {pt.SourceData}")
        print("Pivot now uses", pt.SourceData)

        # 3. calculated fields (e.g. «%») and value fields, as in the source pivot
        have_calc = {cf.Name for cf in items(pt.CalculatedFields())}
        for name, formula in calc_fields:
            if name not in have_calc:
                pt.CalculatedFields().Add(name, formula)
        have_data = {df.Name for df in items(pt.DataFields)}
        for name, source, function, fmt in data_fields:
            if name not in have_data:
                df = pt.AddDataField(pt.PivotFields(source), name, function)
                df.NumberFormat = fmt

        # 4. same filter as the source («Группа скидки»)
        pf = pt.PivotFields(PAGE_FIELD)
        pt.RefreshTable()
        for it in items(pf.PivotItems()):
            if it.Name in visible:
                it.Visible = True
        for it in items(pf.PivotItems()):
            if it.Name not in visible:
                it.Visible = False
        pt.RefreshTable()
        print("Filter «%s»: %s" % (PAGE_FIELD, ", ".join(visible)))

        wb_dst.Save()
        print("Saved:", dst)
        return 0
    finally:
        for wb in (wb_src, wb_dst):
            if wb is not None:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
        excel.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
