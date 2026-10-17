"""Step 1: open Скидки отчёт, enable editing, Refresh All, wait, save, exit Excel.

Schedule this in Task Scheduler at a time that does not clash with other server jobs.
    python refresh_report.py [--date YYYY-MM-DD] [--visible]
"""
import sys

from skidki_report import run_refresh

if __name__ == "__main__":
    sys.exit(run_refresh())
