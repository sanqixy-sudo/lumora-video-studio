"""Allowlisted, secret-free Docker source update; does not deploy or build an image."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
VERSION='20260908-v9.2'

def main():
    target=ROOT/'release'/f'lumora-docker-update-{VERSION}.zip'
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        raise SystemExit('Package already exists; choose a new version rather than overwrite a delivery.')
    files=[]
    for folder in ['app','migrations','tests']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'})
    for name in ['Dockerfile','requirements.txt','alembic.ini','.dockerignore','BRAND.md','LUMORA_PALETTE_CHECK.md','LUMORA_AUTH_CHECK.md','scripts/check_lumora_auth.cjs','scripts/capture_lumora_palette.cjs','scripts/check_lumora_palette.cjs','LUMORA_DOCKER_UPDATE.md','LUMORA_ACCEPTANCE.md','LUMORA_FINAL_CHECK.md','LUMORA_WEB_GUIDELINES.md','LUMORA_MOBILE_CHECK.md','LUMORA_IMAGE_LINKS.md','scripts/audit_web_guidelines.cjs','scripts/check_lumora_guidelines.cjs','scripts/check_lumora_contrast.cjs','scripts/check_lumora_contrast.py','scripts/start_single_container.sh','scripts/init_data_dirs.sh','scripts/build_docker_package.ps1','scripts/preview_ui.py','scripts/preview_studio.py','scripts/preview_usage.py','scripts/check_lumora_reports.cjs','scripts/check_lumora_calendar.cjs','scripts/check_usage_subadmin.cjs','scripts/check_lumora_mobile.cjs','scripts/check_lumora_mobile_flows.cjs','scripts/check_image_confirmation.cjs','scripts/studio_review.html','scripts/render_ui_snapshots.py','scripts/create_studio_preview_clip.cjs','scripts/check_lumora_full.cjs','scripts/check_lumora_interactions.cjs','scripts/check_lumora_stress.cjs','scripts/check_lumora_motion.cjs','scripts/check_lumora_media.cjs','scripts/check_studio_samples.cjs','scripts/check_studio_quality.cjs','scripts/check_studio_delivery.cjs','scripts/probe_wuyin_google_omni.py','scripts/package_lumora.py']:
        files.append(ROOT/name)
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}
    with ZipFile(target,'w',ZIP_DEFLATED) as archive:
        for name in manifest:archive.write(ROOT/name,name)
        archive.writestr('SOURCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(set(archive.namelist()))
        assert not any(name.startswith(('runtime/','data/','.venv/','.git/')) or name in {'.env','docker-compose.yml'} for name in archive.namelist())
        for name,digest in manifest.items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{digest}  {target.name}\n',encoding='ascii')
    print(json.dumps({'package':str(target),'files':len(manifest),'bytes':target.stat().st_size,'sha256':digest},ensure_ascii=False))

if __name__=='__main__':main()
