from pathlib import Path
import sys


WORKERS = Path(__file__).parents[1]
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))
