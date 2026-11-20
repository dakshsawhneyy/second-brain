"""Download the local speech model (resumes; retries on connection drops). Usage: .venv\Scripts\python scripts\fetch-whisper.py [model]"""
import sys
import time
from pathlib import Path

from faster_whisper import WhisperModel

model = sys.argv[1] if len(sys.argv) > 1 else "small"
root = Path(__file__).resolve().parent.parent / "raw" / "models" / "whisper"
for attempt in range(1, 31):
    try:
        WhisperModel(model, device="cpu", compute_type="int8", download_root=str(root))
        print("MODEL READY", model)
        break
    except Exception as e:
        print(f"attempt {attempt} failed: {type(e).__name__}; retrying in 10s", flush=True)
        time.sleep(10)
else:
    raise SystemExit("could not download the model; check the internet connection")
