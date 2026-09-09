"""Package source only; never include deployment secrets or generated media."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

ROOT=Path(__file__).resolve().parents[1]

def main():
    dest=ROOT/'release'; dest.mkdir(exist_ok=True)
    archive=dest/'sora-console-redesign-20260907.zip'
    files=[]
    for folder in ['app','migrations','tests']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'})
    for name in ['scripts/start_single_container.sh','scripts/init_data_dirs.sh','scripts/build_docker_package.ps1','scripts/probe_wuyin_google_omni.py','scripts/preview_ui.py','scripts/render_ui_snapshots.py','scripts/check_ui.cjs','scripts/package_redesign.py','Dockerfile','requirements.txt','alembic.ini','.dockerignore','REDESIGN_UPDATE.md']:
        files.append(ROOT/name)
    with ZipFile(archive,'w',ZIP_DEFLATED) as z:
        for file in sorted(set(files)): z.write(file,file.relative_to(ROOT).as_posix())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n',encoding='ascii')
    with ZipFile(archive) as z:
        assert z.testzip() is None
        assert all(not n.startswith(('data/','runtime/','.venv/')) and n not in {'.env','docker-compose.yml'} for n in z.namelist())
    print(f'{archive}\n{len(files)} source files; SHA-256 {digest}')

if __name__=='__main__': main()
