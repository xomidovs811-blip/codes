"""
The "Zayavkalar" backup archive.

Every zayavka is kept as one Excel file in a folder per month (by the
zayavka's date):

    Zayavkalar/2026-03/Zayavka-15-3-14-Я-К.xlsx

with these sheets:
    Ma'lumot      - the key details and the list of versions
    Version 1..N  - each earlier saved version, laid out like the sent file
    Last version  - the current version (opens first)
    _data         - very hidden: the exact saved data as JSON, which is
                    what "Back-up qilish" reads to restore a zayavka

The file is rewritten after every save (archive_zayavka), and on start-up
sync_archive() writes any file that is missing or out of date - so all
zayavkas saved before this existed get archived too. _index.json in the
archive folder remembers what each file holds, so that check is quick.

restore_files() is the other direction: it re-creates zayavkas from chosen
archive files, but only those whose Номер заявки is NOT in the system yet.
"""
import json
import logging
import os
import re
import tempfile
import threading
from datetime import date, datetime, timedelta
from typing import List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config import ARCHIVE_DIR, EXCEL_SHEET_PASSWORD
from app.db import SessionLocal
from app.excel_gen import fill_sheet, protect_workbook
from app.models import NameOption, Zayavka, ZayavkaItem, ZayavkaVersion

logger = logging.getLogger("zayavka-archive")

FORMAT_VERSION = 1
DATA_SHEET = "_data"
INDEX_FILE = "_index.json"
CHUNK = 30000            # an Excel cell holds at most 32,767 characters
TASHKENT = timedelta(hours=5)
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

_lock = threading.Lock()   # one archive write at a time (saves, start-up sync, restore)

META_FIELDS = (
    "number", "object_name", "from_whom", "to_whom", "payment_type",
    "inspector", "cashier", "tech_supervisor", "created_by_tg_id", "created_by_name",
    "deleted_by",
)
ITEM_FIELDS = (
    "row_no", "product_name", "supplier", "block", "floor", "unit", "qty", "price",
    "total", "advance", "remainder", "work_type", "comment",
)

BOLD = Font(name="Calibri", size=11, bold=True)
HEAD_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
LABEL_FILL = PatternFill("solid", fgColor="EEF5FB")
THIN = Side(style="thin", color="B7C9DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ---------- paths ----------

def safe_file_part(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", text or "").strip() or "zayavka"


def relative_path(z: Zayavka) -> str:
    """'2026-03/Zayavka-<number>.xlsx' - always with '/' (also the id used by the page)."""
    return f"{z.zayavka_date:%Y-%m}/Zayavka-{safe_file_part(z.number)}.xlsx"


def _full_path(rel: str) -> str:
    """The real path of an archive file, refusing anything outside the archive folder."""
    root = os.path.realpath(ARCHIVE_DIR)
    path = os.path.realpath(os.path.join(root, *rel.replace("\\", "/").split("/")))
    if os.path.commonpath([root, path]) != root or not path.lower().endswith(".xlsx"):
        raise ValueError("noto'g'ri fayl yo'li")
    return path


def _local(dt: Optional[datetime]) -> str:
    return (dt + TASHKENT).strftime("%d.%m.%Y %H:%M") if dt else ""


# ---------- index (what each archive file currently holds) ----------

def _load_index() -> dict:
    try:
        with open(os.path.join(ARCHIVE_DIR, INDEX_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_index(index: dict) -> None:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(ARCHIVE_DIR, INDEX_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)


def _signature(z: Zayavka, versions: list) -> list:
    """Changes whenever the archive file would come out different."""
    last = versions[-1] if versions else None
    return [
        len(versions),
        last.created_at.isoformat() if last and last.created_at else None,
        z.deleted_at.isoformat() if z.deleted_at else None,
        relative_path(z),
    ]


# ---------- building one archive file ----------

def _payload(z: Zayavka, versions: list) -> dict:
    meta = {k: getattr(z, k) for k in META_FIELDS}
    meta["zayavka_date"] = z.zayavka_date.isoformat()
    meta["created_at"] = z.created_at.isoformat() if z.created_at else None
    meta["deleted_at"] = z.deleted_at.isoformat() if z.deleted_at else None
    return {
        "format": FORMAT_VERSION,
        "archived_at": datetime.utcnow().isoformat(),
        "zayavka": meta,
        "versions": [
            {
                "version_no": v.version_no,
                "action": v.action,
                "saved_by": v.saved_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "snapshot": v.snapshot,
            }
            for v in versions
        ],
    }


def _info_sheet(ws, z: Zayavka, versions: list) -> None:
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 24
    for col, width in zip("BCDEFG", (16, 22, 26, 12, 18, 18)):
        ws.column_dimensions[col].width = width
    ws["A1"] = "ZAYAVKA ARXIVI"
    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="1F4E78")
    rows = [
        ("Номер заявки", z.number),
        ("Название объекта", z.object_name),
        ("Дата", z.zayavka_date.strftime("%d.%m.%Y")),
        ("От кого", z.from_whom),
        ("Кому", z.to_whom),
        ("Вид оплаты", z.payment_type),
        ("Yuborgan", z.created_by_name or ""),
        ("Yaratilgan", _local(z.created_at)),
        ("Versiyalar soni", str(len(versions))),
        ("Holati", f"O'chirilgan ({_local(z.deleted_at)}, {z.deleted_by or ''})" if z.deleted_at else "Faol"),
        ("Arxivlangan", _local(datetime.utcnow())),
    ]
    for i, (label, value) in enumerate(rows, start=3):
        a = ws.cell(row=i, column=1, value=label)
        a.font, a.fill, a.border = BOLD, LABEL_FILL, BORDER
        b = ws.cell(row=i, column=2, value=value)
        b.border = BORDER
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=4)

    top = 3 + len(rows) + 1
    heads = ["Varaq", "Versiya", "Saqlangan", "Kim saqlagan", "Qatorlar", "Общая сумма", "Остатка"]
    for c, h in enumerate(heads, start=1):
        cell = ws.cell(row=top, column=c, value=h)
        cell.font, cell.fill, cell.border = HEAD_FONT, HEAD_FILL, BORDER
        cell.alignment = Alignment(horizontal="center")
    for r, v in enumerate(versions, start=top + 1):
        s = v.summary()
        is_last = v is versions[-1]
        values = [
            "Last version" if is_last else f"Version {v.version_no}",
            v.version_no,
            _local(v.created_at),
            v.saved_by or "",
            s["rows"],
            round(s["total"], 2),
            round(s["remainder"], 2),
        ]
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = BORDER
            if c >= 6:
                cell.number_format = "#,##0"
            if is_last:
                cell.font = BOLD
    _print_landscape(ws)
    if EXCEL_SHEET_PASSWORD:
        ws.protection.sheet = True
        ws.protection.password = EXCEL_SHEET_PASSWORD


def _print_landscape(ws) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_archive_workbook(z: Zayavka, versions: list) -> Workbook:
    wb = Workbook()
    info = wb.active
    info.title = "Ma'lumot"
    _info_sheet(info, z, versions)

    for v in versions[:-1]:
        fill_sheet(wb.create_sheet(f"Version {v.version_no}"), v.data())
    last = wb.create_sheet("Last version")
    fill_sheet(last, versions[-1].data() if versions else z.to_dict())
    wb.active = wb.sheetnames.index("Last version")
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = ws is last

    data_ws = wb.create_sheet(DATA_SHEET)
    text = json.dumps(_payload(z, versions), ensure_ascii=False, default=str)
    for i in range(0, len(text), CHUNK):
        data_ws.cell(row=i // CHUNK + 1, column=1, value=text[i:i + CHUNK])
    data_ws.sheet_state = "veryHidden"
    protect_workbook(wb)
    return wb


def archive_zayavka(zayavka_id: int) -> Optional[str]:
    """(Re)writes one zayavka's archive file. Never raises - a failure is logged and
    retried by the next start-up sync (e.g. while the file is open in Excel)."""
    with _lock:
        db = SessionLocal()
        tmp = None
        try:
            z = db.query(Zayavka).filter(Zayavka.id == zayavka_id).first()
            if z is None:
                return None
            versions = sorted(z.versions, key=lambda v: v.version_no)
            rel = relative_path(z)
            path = _full_path(rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(path))
            os.close(fd)
            build_archive_workbook(z, versions).save(tmp)
            os.replace(tmp, path)
            tmp = None
            index = _load_index()
            index[str(z.id)] = {"number": z.number, "path": rel, "sig": _signature(z, versions)}
            _save_index(index)
            return path
        except Exception:
            logger.exception("Could not archive zayavka %s", zayavka_id)
            return None
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            db.close()


def archive_later(zayavka_id: int) -> None:
    """Writes the archive file in the background so saving stays fast."""
    threading.Thread(target=archive_zayavka, args=(zayavka_id,), daemon=True).start()


def sync_archive() -> int:
    """Archives every zayavka whose file is missing or out of date. Returns how many were written."""
    db = SessionLocal()
    try:
        index = _load_index()
        todo = []
        for z in db.query(Zayavka).all():
            versions = sorted(z.versions, key=lambda v: v.version_no)
            entry = index.get(str(z.id))
            if (
                not entry
                or entry.get("sig") != _signature(z, versions)
                or not os.path.exists(_full_path(entry.get("path", relative_path(z))))
            ):
                todo.append(z.id)
    finally:
        db.close()
    written = sum(1 for zid in todo if archive_zayavka(zid))
    if todo:
        logger.info("Archive sync: %d of %d zayavka files written to %s", written, len(todo), ARCHIVE_DIR)
    return written


def sync_archive_later() -> None:
    threading.Thread(target=sync_archive, daemon=True).start()


# ---------- listing and restoring ----------

def list_archive(db) -> dict:
    """The archive folder as months -> files, each marked whether its zayavka is in the system."""
    numbers = {n for (n,) in db.query(Zayavka.number).all()}
    by_path = {e["path"]: e["number"] for e in _load_index().values() if "path" in e}
    months = []
    if os.path.isdir(ARCHIVE_DIR):
        for month in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
            folder = os.path.join(ARCHIVE_DIR, month)
            if not MONTH_RE.match(month) or not os.path.isdir(folder):
                continue
            files = []
            for name in sorted(os.listdir(folder)):
                if not name.lower().endswith(".xlsx") or name.startswith(("~$", "_", ".")):
                    continue
                rel = f"{month}/{name}"
                number = by_path.get(rel) or (name[len("Zayavka-"):-5] if name.startswith("Zayavka-") else name[:-5])
                files.append({"path": rel, "name": name, "number": number, "in_system": number in numbers})
            if files:
                months.append({
                    "month": month,
                    "files": files,
                    "missing": sum(1 for f in files if not f["in_system"]),
                })
    return {
        "archive_dir": os.path.abspath(ARCHIVE_DIR),
        "months": months,
        "total_files": sum(len(m["files"]) for m in months),
        "total_missing": sum(m["missing"] for m in months),
    }


def read_archive_file(path: str) -> dict:
    wb = load_workbook(path, read_only=True)
    try:
        if DATA_SHEET not in wb.sheetnames:
            raise ValueError("bu arxiv fayli emas (ichida saqlangan ma'lumot yo'q)")
        text = "".join(row[0] or "" for row in wb[DATA_SHEET].iter_rows(min_col=1, max_col=1, values_only=True))
    finally:
        wb.close()
    data = json.loads(text)
    if data.get("format") != FORMAT_VERSION or not data.get("versions"):
        raise ValueError("arxiv fayli formati tanish emas")
    return data


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _restore_one(db, data: dict) -> Zayavka:
    meta = data["zayavka"]
    versions = sorted(data["versions"], key=lambda v: v["version_no"])
    last = json.loads(versions[-1]["snapshot"])

    z = Zayavka(**{k: meta.get(k) for k in META_FIELDS})
    z.zayavka_date = date.fromisoformat(meta["zayavka_date"])
    z.created_at = _dt(meta.get("created_at")) or datetime.utcnow()
    z.deleted_at = _dt(meta.get("deleted_at"))
    z.items = [ZayavkaItem(**{k: item.get(k) for k in ITEM_FIELDS}) for item in last.get("items", [])]
    db.add(z)
    db.flush()
    for v in versions:
        db.add(ZayavkaVersion(
            zayavka_id=z.id,
            version_no=v["version_no"],
            action=v.get("action") or "created",
            saved_by=v.get("saved_by"),
            created_at=_dt(v.get("created_at")) or z.created_at,
            snapshot=v["snapshot"],
        ))
    # an object that only exists in the archive becomes pickable/filterable again
    from app.access import all_objects
    if z.object_name and z.object_name not in all_objects():
        db.add(NameOption(category="object", name=z.object_name))
    return z


def restore_files(rel_paths: List[str]) -> List[dict]:
    """
    Re-creates the zayavkas in the chosen archive files - only those whose
    Номер заявки is not in the system; existing ones are left untouched.
    Returns one result row per file for the report.
    """
    results = []
    seen = set()
    db = SessionLocal()
    try:
        for rel in rel_paths:
            rel = rel.replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            row = {"file": rel.split("/")[-1], "month": rel.split("/")[0], "number": "", "object": "",
                   "date": "", "from_whom": "", "versions": 0, "status": "error", "note": ""}
            try:
                data = read_archive_file(_full_path(rel))
                meta = data["zayavka"]
                row.update(number=meta["number"], object=meta.get("object_name") or "",
                           date=meta.get("zayavka_date") or "", from_whom=meta.get("from_whom") or "",
                           versions=len(data["versions"]))
                if db.query(Zayavka.id).filter(Zayavka.number == meta["number"]).first():
                    row["status"], row["note"] = "exists", "Tizimda bor - o'zgartirilmadi"
                else:
                    z = _restore_one(db, data)
                    db.commit()
                    row["status"] = "restored"
                    row["note"] = "Tiklandi" + (" (o'chirilgan holatda)" if z.deleted_at else "")
            except FileNotFoundError:
                db.rollback()
                row["note"] = "Fayl topilmadi"
            except ValueError as e:      # not an archive file / bad path - explained in the report
                db.rollback()
                logger.warning("Restore skipped %s: %s", rel, e)
                row["note"] = str(e)[:300]
            except Exception as e:
                db.rollback()
                logger.exception("Restore failed for %s", rel)
                row["note"] = str(e)[:300] or e.__class__.__name__
            results.append(row)
    finally:
        db.close()
    return results


def build_restore_report(results: List[dict], restored_by: str, when: datetime, out_dir: str) -> str:
    """The Excel report of a "Back-up qilish" run."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Back-up hisobot"
    ws.sheet_view.showGridLines = False
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("restored", "exists", "error")}

    ws["A1"] = "BACK-UP (TIKLASH) HISOBOTI"
    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="1F4E78")
    summary = [
        ("Sana", when.strftime("%d.%m.%Y %H:%M")),
        ("Bajargan", restored_by),
        ("Arxiv papkasi", os.path.abspath(ARCHIVE_DIR)),
        ("Tanlangan fayllar", len(results)),
        ("Tiklandi (yangi qo'shildi)", counts["restored"]),
        ("Tizimda bor edi (o'tkazib yuborildi)", counts["exists"]),
        ("Xatolik", counts["error"]),
    ]
    for i, (label, value) in enumerate(summary, start=3):
        a = ws.cell(row=i, column=1, value=label)
        a.font, a.fill, a.border = BOLD, LABEL_FILL, BORDER
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=3)
        b = ws.cell(row=i, column=4, value=str(value))
        b.border = BORDER
        b.alignment = Alignment(horizontal="left")
        ws.merge_cells(start_row=i, start_column=4, end_row=i, end_column=10)

    heads = ["№", "Fayl", "Oy", "Номер заявки", "Название объекта", "Дата", "От кого", "Versiyalar", "Natija", "Izoh"]
    widths = [5, 34, 10, 20, 30, 12, 22, 11, 16, 50]
    top = 3 + len(summary) + 1
    for c, (h, w) in enumerate(zip(heads, widths), start=1):
        cell = ws.cell(row=top, column=c, value=h)
        cell.font, cell.fill, cell.border = HEAD_FONT, HEAD_FILL, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = w
    status_text = {"restored": "✅ Tiklandi", "exists": "⏭ Bor edi", "error": "❌ Xatolik"}
    status_fill = {
        "restored": PatternFill("solid", fgColor="D9EAD3"),
        "exists": PatternFill("solid", fgColor="EDEDED"),
        "error": PatternFill("solid", fgColor="F4CCCC"),
    }
    for n, r in enumerate(results, start=1):
        d = r["date"]
        try:
            d = date.fromisoformat(d).strftime("%d.%m.%Y") if d else ""
        except ValueError:
            pass
        values = [n, r["file"], r["month"], r["number"], r["object"], d, r["from_whom"],
                  r["versions"], status_text[r["status"]], r["note"]]
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=top + n, column=c, value=value)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=c in (2, 5, 10))
            if c == 9:
                cell.fill = status_fill[r["status"]]
    ws.freeze_panes = ws.cell(row=top + 1, column=1)
    ws.auto_filter.ref = f"A{top}:J{top + max(len(results), 1)}"
    _print_landscape(ws)

    path = os.path.join(out_dir, f"Backup-hisobot-{when:%Y-%m-%d_%H-%M}.xlsx")
    wb.save(path)
    return path
