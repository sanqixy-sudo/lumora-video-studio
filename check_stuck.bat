@echo off
cd /d C:\Users\Administrator\Desktop\sora
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from app.db import SessionLocal; from sqlalchemy import text; db = SessionLocal(); r = db.execute(text('SELECT id, status, progress, updated_at FROM jobs WHERE status IN (''submitted'', ''polling'', ''remote_completed'') ORDER BY updated_at ASC LIMIT 10')); print('\n活跃任务:'); [print(f'ID={row.id} status={row.status} progress={row.progress}%% updated={row.updated_at}') for row in r]; print('\n完成')"
pause
