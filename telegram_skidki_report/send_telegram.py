"""Step 2: send the refreshed Скидки отчёт file + report text to the Telegram group.

Schedule this AFTER refresh_report.py has finished. It refuses to send a file
that was not refreshed for yesterday (use --force to send it anyway).
    python send_telegram.py [--date YYYY-MM-DD] [--force]
"""
import sys

from skidki_report import run_send

if __name__ == "__main__":
    sys.exit(run_send())
