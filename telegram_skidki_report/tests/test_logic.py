import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import refresh_report as rr  # noqa: E402
import send_telegram as st  # noqa: E402

FORMULA = (
    'let\n'
    '    #"Строки с примененным фильтром" = Table.SelectRows(#"Измененный тип", each [Дата2] > #date(2026, 9, 30)),\n'
    '    #"Строки с примененным фильтром2" = Table.SelectRows(#"Строки с примененным фильтром", each ([Сумма скидки] <> null)),\n'
    'in\n    x'
)


class Refresh(unittest.TestCase):
    def test_month_filter(self):
        new = rr.month_filter(FORMULA, dt.date(2026, 12, 5))
        self.assertIn("each [Дата2] >= #date(2026, 12, 1) and [Дата2] < #date(2027, 1, 1)),\n", new)
        self.assertIn("each ([Сумма скидки] <> null)", new)
        self.assertEqual(rr.month_filter(new, dt.date(2026, 12, 31)), new)
        self.assertIn("#date(2026, 10, 1)", rr.month_filter(FORMULA.replace("\n", "\r\n"), dt.date(2026, 10, 1)))
        with self.assertRaises(RuntimeError):
            rr.month_filter("let x = 1 in x", dt.date(2026, 10, 1))

    def test_monthly_files(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(rr, "REPORT_FOLDER", d):
            for m in ["2026-08", "2026-09", "2026-11"]:
                open(os.path.join(d, f"Скидки отчёт {m}.xlsx"), "w").close()
            self.assertTrue(rr.previous_monthly_file(dt.date(2026, 10, 31)).endswith("2026-09.xlsx"))
            self.assertIsNone(rr.previous_monthly_file(dt.date(2026, 8, 1)))
            path = rr.get_month_file(dt.date(2026, 10, 2))  # new month -> copied from September
            self.assertTrue(path.endswith("Скидки отчёт 2026-10.xlsx") and os.path.exists(path))

    def test_range_to_text(self):
        vals = ((None,), ("📊 ОТЧЁТ",), (None,), ("Итого¶",), ("",), (None,))
        self.assertEqual(rr.range_to_text(vals), "📊 ОТЧЁТ\n\nИтого")


class Send(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.state = os.path.join(d, "state")
        os.makedirs(self.state)
        open(os.path.join(d, "Скидки отчёт 2026-10.xlsx"), "wb").close()
        self.calls = []
        self.patches = [
            mock.patch.object(st, "REPORT_FOLDER", d),
            mock.patch.object(st, "STATE_DIR", self.state),
            mock.patch.object(st, "LOG_FILE", os.path.join(d, "logs", "send.log")),
            mock.patch.object(st, "BOT_TOKEN", "1:x"),
            mock.patch.object(st, "telegram", lambda m, data, files=None: self.calls.append(m)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for h in list(st.log.handlers):
            h.close()
            st.log.removeHandler(h)
        self.tmp.cleanup()

    def run_send(self, *args):
        with mock.patch.object(sys, "argv", ["send_telegram.py", "2026-10-16", *args]):
            return st.main()

    def test_not_refreshed_is_not_sent(self):
        self.assertEqual(self.run_send(), 1)
        self.assertEqual(self.calls, [])

    def test_sends_once(self):
        with open(os.path.join(self.state, "refreshed_2026-10-16.txt"), "w", encoding="utf-8") as f:
            f.write("📊 ОТЧЁТ")
        self.assertEqual(self.run_send(), 0)
        self.assertEqual(self.calls, ["sendDocument", "sendMessage"])
        self.assertEqual(self.run_send(), 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.run_send("--force"), 0)
        self.assertEqual(len(self.calls), 4)

    def test_split_text(self):
        text = "\n".join(f"line {i:04d}" for i in range(1000))
        parts = st.split_text(text, 100)
        self.assertTrue(all(len(p) <= 100 for p in parts))
        self.assertEqual("\n".join(parts), text)
        self.assertTrue(all(len(p) <= 10 for p in st.split_text("x" * 25, 10)))


if __name__ == "__main__":
    unittest.main()
