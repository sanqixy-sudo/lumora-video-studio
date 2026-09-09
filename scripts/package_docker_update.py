"""Build a source update ZIP for the existing server's Docker Compose deployment."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

from package_redesign import main as package_source

ROOT = Path(__file__).resolve().parents[1]


def main():
    package_source()
    name = 'sora-console-docker-update-20260907.zip'
    source = ROOT / 'release/sora-console-redesign-20260907.zip'
    target = ROOT / 'release' / name
    instructions = (ROOT / 'REDESIGN_UPDATE.md').read_text(encoding='utf-8')
    instructions = instructions.replace('sora-console-redesign-20260907.zip', name)
    instructions = instructions.replace('源码更新包在', 'Docker 源码更新包在')
    instructions += '\n此 ZIP 沿用现有项目的服务器构建更新方式，不是 docker load 使用的预构建镜像。请保留服务器当前 Compose 配置。\n'
    with ZipFile(source) as original, ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for item in original.infolist():
            content = original.read(item.filename)
            if item.filename == 'REDESIGN_UPDATE.md':
                content = instructions.encode('utf-8')
            elif item.filename == '.dockerignore':
                content += b'\ndata/\n'
            archive.writestr(item.filename, content)
        archive.writestr('SERVER_DOCKER_UPDATE.md', instructions.encode('utf-8'))
        archive.write(Path(__file__), 'scripts/package_docker_update.py')
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(not n.startswith(('data/', 'runtime/', '.venv/')) and n not in {'.env', 'docker-compose.yml', 'docker-compose.migrate.yml'} for n in names)
        for required in ['Dockerfile', 'requirements.txt', 'alembic.ini', 'scripts/start_single_container.sh', 'scripts/init_data_dirs.sh', 'SERVER_DOCKER_UPDATE.md', 'app/static/workbench/tokens.css']:
            assert required in names, required
        assert 'sora-console-redesign-20260907.zip' not in archive.read('SERVER_DOCKER_UPDATE.md').decode('utf-8')
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{digest}  {name}\n', encoding='ascii')
    (target.parent / 'DOCKER_UPDATE_20260907.md').write_text(instructions, encoding='utf-8')
    print(f'Docker update: {target}\nFiles: {len(names)}\nBytes: {target.stat().st_size}\nSHA-256: {digest}')


if __name__ == '__main__':
    main()
