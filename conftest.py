"""pytest root conftest — 把專案根目錄加入 sys.path，讓測試可以 `from helpers import ...`。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
