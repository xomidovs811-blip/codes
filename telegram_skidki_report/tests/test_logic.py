import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import skidki_report as sr  # noqa: E402

FORMULA = (
    'let\n'
    '    #"Измененный тип" = Table.TransformColumnTypes(#"Строки с примененным фильтром1",{{"Дата2", type date}}),\n'
    '    #"Строки с примененным фильтром" = Table.SelectRows(#"Измененный тип", each [Дата2] > #date(2026, 9, 30)),\n'
    '    #"Строки с примененным фильтром2" = Table.SelectRows(#"Строки с примененным фильтром", each ([Сумма скидки] <> null)),\n'
    'in\n    x'
)


class DateLogic(unittest.TestCase):
    def test_yesterday(self):
        self.assertEqual(sr.report_date_for(dt.date(2026, 10, 17)), dt.date(2026, 10, 16))

    def test_first_of_month_reports_previous_month(self):
        d = sr.report_date_for(dt.date(2026, 11, 1))
        self.assertEqual(sr.month_key(d), "2026-10")
        self.assertEqual(sr.month_key(sr.report_date_for(dt.date(2026, 11, 2))), "2026-11")
        self.assertEqual(sr.month_key(sr.report_date_for(dt.date(2027, 1, 1))), "2026-12")

    def test_month_bounds_december(self):
        self.assertEqual(sr.month_bounds(dt.date(2026, 12, 31)), (dt.date(2026, 12, 1), dt.date(2027, 1, 1)))

    def test_excel_serial(self):
        self.assertEqual(sr.to_excel_serial(dt.date(2026, 10, 15)), 46310)

    def test_file_name(self):
        p = sr.monthly_file_path("X", "Скидки отчёт", dt.date(2026, 10, 5))
        self.assertEqual(os.path.basename(p), "Скидки отчёт 2026-10.xlsx")


class PreviousFile(unittest.TestCase):
    def test_picks_latest_earlier_month(self):
        with tempfile.TemporaryDirectory() as d:
            for m in ["2026-08", "2026-09", "2026-11"]:
                open(os.path.join(d, f"Скидки отчёт {m}.xlsx"), "w").close()
            open(os.path.join(d, "other.xlsx"), "w").close()
            got = sr.find_previous_monthly_file(d, "Скидки отчёт", dt.date(2026, 10, 31))
            self.assertTrue(got.endswith("Скидки отчёт 2026-09.xlsx"))
            self.assertIsNone(sr.find_previous_monthly_file(d, "Скидки отчёт", dt.date(2026, 8, 1)))


class MonthFilter(unittest.TestCase):
    def test_rewrites_original_filter(self):
        new = sr.set_month_filter(FORMULA, dt.date(2026, 11, 3))
        self.assertIn('each [Дата2] >= #date(2026, 11, 1) and [Дата2] < #date(2026, 12, 1)),\n', new)
        self.assertNotIn("#date(2026, 9, 30)", new)
        self.assertIn('each ([Сумма скидки] <> null)', new)

    def test_idempotent_and_reapplicable(self):
        a = sr.set_month_filter(FORMULA, dt.date(2026, 11, 3))
        self.assertEqual(sr.set_month_filter(a, dt.date(2026, 11, 20)), a)
        b = sr.set_month_filter(a, dt.date(2026, 12, 1))
        self.assertIn("#date(2026, 12, 1) and [Дата2] < #date(2027, 1, 1)", b)

    def test_crlf(self):
        new = sr.set_month_filter(FORMULA.replace("\n", "\r\n"), dt.date(2026, 10, 1))
        self.assertIn("#date(2026, 10, 1) and", new)

    def test_missing_filter_raises(self):
        with self.assertRaises(RuntimeError):
            sr.set_month_filter("let x = 1 in x", dt.date(2026, 10, 1))


class Text(unittest.TestCase):
    def test_range_values(self):
        vals = (("📊 ОТЧЁТ",), ("📅 15.10.2026",), (None,), ("Итого¶",), ("",), (None,))
        self.assertEqual(sr.range_values_to_text(vals), "📊 ОТЧЁТ\n📅 15.10.2026\n\nИтого")

    def test_split(self):
        text = "\n".join(f"line {i:04d}" for i in range(1000))
        chunks = sr.split_message(text, 100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual("\n".join(chunks), text)
        self.assertEqual(sr.split_message("short"), ["short"])
        self.assertTrue(all(len(c) <= 10 for c in sr.split_message("x" * 25, 10)))


class State(unittest.TestCase):
    def test_sent_state(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.json")
            day = dt.date(2026, 10, 16)
            self.assertFalse(sr.already_sent(f, day))
            sr.mark_sent(f, day)
            self.assertTrue(sr.already_sent(f, day))
            self.assertFalse(sr.already_sent(f, dt.date(2026, 10, 17)))


if __name__ == "__main__":
    unittest.main()
