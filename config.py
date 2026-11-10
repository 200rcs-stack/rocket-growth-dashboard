from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'raw_data'
MASTER = ROOT / 'master_data'
DATA = ROOT / 'data'
DOWNLOADS = Path.home() / 'Downloads'
KST = ZoneInfo('Asia/Seoul')
for folder in (RAW, MASTER, DATA):
    folder.mkdir(exist_ok=True)

def now():
    return datetime.now(KST)
