import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import refresh_report as rr  # noqa: E402
import send_telegram as st  # noqa: E402
import delete_last_report as dl  # noqa: E402

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


class RunLock(unittest.TestCase):
    def test_single_run_lock(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(rr, "STATE_DIR", d):
            self.assertTrue(rr.single_run_lock())
            self.assertFalse(rr.single_run_lock())  # second run at the same time is skipped
            lock = os.path.join(d, "refresh.lock")
            old = os.path.getmtime(lock) - 3600
            os.utime(lock, (old, old))
            self.assertTrue(rr.single_run_lock())  # stale lock from a crashed run is taken over


class CatchUp(unittest.TestCase):
    def test_pending_days(self):
        with tempfile.TemporaryDirectory() as d:
            for mod in (rr, st):
                with mock.patch.object(mod, "STATE_DIR", d):
                    today = dt.date(2026, 10, 19)
                    self.assertEqual(mod.pending_days(today), [dt.date(2026, 10, 18)])  # nothing sent yet
                    open(os.path.join(d, "sent_2026-10-14.txt"), "w").close()
                    self.assertEqual(mod.pending_days(today), [dt.date(2026, 10, d_) for d_ in (15, 16, 17, 18)])
                    open(os.path.join(d, "sent_2026-10-18.txt"), "w").close()
                    self.assertEqual(mod.pending_days(today), [])
                    with mock.patch.object(mod, "MAX_CATCHUP_DAYS", 2):
                        self.assertEqual(mod.pending_days(dt.date(2026, 10, 25)),
                                         [dt.date(2026, 10, 23), dt.date(2026, 10, 24)])
                    for f in os.listdir(d):
                        os.remove(os.path.join(d, f))


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
            mock.patch.object(st, "telegram", self.fake_telegram),
        ]
        for p in self.patches:
            p.start()

    def fake_telegram(self, method, data, files=None):
        self.calls.append(method)
        return {"message_id": 100 + len(self.calls)}

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

    def test_delete_last_report(self):
        with open(os.path.join(self.state, "refreshed_2026-10-16.txt"), "w", encoding="utf-8") as f:
            f.write("📊 ОТЧЁТ")
        self.assertEqual(self.run_send(), 0)
        deleted = []
        with mock.patch.object(dl, "STATE_DIR", self.state), \
                mock.patch.object(dl, "LOG_FILE", os.path.join(self.tmp.name, "logs", "delete.log")), \
                mock.patch.object(dl, "BOT_TOKEN", "1:x"), \
                mock.patch.object(dl, "delete_message", deleted.append), \
                mock.patch.object(sys, "argv", ["delete_last_report.py"]):
            self.assertEqual(dl.main(), 0)
        for h in list(dl.log.handlers):
            h.close()
            dl.log.removeHandler(h)
        self.assertEqual(deleted, [101, 102])
        self.assertFalse(os.path.exists(os.path.join(self.state, "sent_2026-10-16.txt")))
        self.assertEqual(self.run_send(), 0)  # can be sent again
        self.assertEqual(len(self.calls), 4)

    def test_catch_up_sends_each_day_in_order(self):
        open(os.path.join(self.state, "sent_2026-10-15.txt"), "w").close()
        os.makedirs(os.path.join(self.state, "files"))
        for day in ("16", "17", "18"):
            with open(os.path.join(self.state, f"refreshed_2026-10-{day}.txt"), "w", encoding="utf-8") as f:
                f.write(day)
            open(os.path.join(self.state, "files", f"Скидки отчёт 2026-10-{day}.xlsx"), "wb").close()
        with mock.patch.object(sys, "argv", ["send_telegram.py"]), mock.patch.object(st.time, "sleep"), \
                mock.patch.object(st.dt, "date", wraps=dt.date) as fake_date:
            fake_date.today.return_value = dt.date(2026, 10, 19)
            fake_date.fromisoformat = dt.date.fromisoformat
            self.assertEqual(st.main(), 0)
        self.assertEqual(len(self.calls), 6)  # 3 days x (file + text)
        for day in ("16", "17", "18"):
            self.assertTrue(os.path.exists(os.path.join(self.state, f"sent_2026-10-{day}.txt")))
        self.assertEqual(os.listdir(os.path.join(self.state, "files")), [])  # day copies cleaned up

    def test_catch_up_stops_at_missing_refresh(self):
        open(os.path.join(self.state, "sent_2026-10-16.txt"), "w").close()
        with open(os.path.join(self.state, "refreshed_2026-10-18.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        with mock.patch.object(sys, "argv", ["send_telegram.py"]), \
                mock.patch.object(st.dt, "date", wraps=dt.date) as fake_date:
            fake_date.today.return_value = dt.date(2026, 10, 19)
            fake_date.fromisoformat = dt.date.fromisoformat
            self.assertEqual(st.main(), 1)  # 17th not refreshed -> nothing sent, order kept
        self.assertEqual(self.calls, [])

    def test_split_text(self):
        text = "\n".join(f"line {i:04d}" for i in range(1000))
        parts = st.split_text(text, 100)
        self.assertTrue(all(len(p) <= 100 for p in parts))
        self.assertEqual("\n".join(parts), text)
        self.assertTrue(all(len(p) <= 10 for p in st.split_text("x" * 25, 10)))


if __name__ == "__main__":
    unittest.main()
