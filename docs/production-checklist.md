# Telegram DL Guard Production Checklist

- Local verification passes: `venv\Scripts\python.exe scripts\verify_local.py`
- Live read-only smoke passes: `venv\Scripts\python.exe scripts\smoke_telegram_live.py read-only`
- Live transfer smoke passes: `venv\Scripts\python.exe scripts\smoke_telegram_live.py transfer`
- Live fallback smoke passes: `venv\Scripts\python.exe scripts\smoke_telegram_live.py fallback`
- `QUEUE_SIZE` is reviewed for the target machine.
- `UPLOAD_WORKERS` is reviewed for the target machine.
- `PROCESSING_MODE` is confirmed.
- `TARGET_GROUPS` is selected from live group sync.
- `STORAGE_GROUP_ID` is verified.
- Cleanup mode is verified.
