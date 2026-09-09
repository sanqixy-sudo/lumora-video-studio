"""Read only enabled shared presets, then prepare bounded local preview thumbnails."""
from pathlib import Path
import os
import getpass, json, shlex, io
from concurrent.futures import ThreadPoolExecutor
import paramiko, httpx
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'design/mature/static/login-materials'
def main():
    password=getpass.getpass('SSH password: ')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(ROOT/'runtime/ssh_known_hosts'))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(os.environ['LUMORA_SSH_HOST'],port=int(os.getenv('LUMORA_SSH_PORT','22')),username=os.environ['LUMORA_SSH_USER'],password=password,timeout=15)
    code="""import json
from sqlalchemy import text
from app.db import engine
with engine.connect() as c:
 rows=c.execute(text("SELECT image_url FROM reference_image_presets WHERE owner_user_id IS NULL AND status='active' ORDER BY id DESC LIMIT 48")).fetchall()
 print(json.dumps([r[0] for r in rows]))
"""
    command="sudo -S -p '' docker exec sora-v2-sora-1 /opt/venv/bin/python -c "+shlex.quote(code)
    stdin,stdout,stderr=ssh.exec_command(command,timeout=30)
    stdin.write(password+'\n');stdin.flush();stdin.channel.shutdown_write()
    raw=stdout.read();status=stdout.channel.recv_exit_status();ssh.close();password=None
    if status: raise RuntimeError('Shared preset read failed: '+stderr.read().decode()[:300])
    urls=list(dict.fromkeys(json.loads(raw)))
    OUT.mkdir(parents=True,exist_ok=True)
    def thumbnail(pair):
        index,url=pair
        try:
            with httpx.Client(timeout=18,follow_redirects=True) as client:
                with client.stream('GET',url) as response:
                    response.raise_for_status();chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>12_000_000:raise ValueError('image too large')
                        chunks.append(chunk)
            img=Image.open(io.BytesIO(b''.join(chunks)))
            if img.width*img.height>40_000_000:raise ValueError('pixel limit')
            img=ImageOps.exif_transpose(img).convert('RGB');img.thumbnail((640,720))
            name=f'material-{index:02d}.webp';img.save(OUT/name,'WEBP',quality=82)
            return {'src':'/static/mature/login-materials/'+name,'width':img.width,'height':img.height}
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        images=[item for item in pool.map(thumbnail,enumerate(urls)) if item]
    (OUT/'manifest.json').write_text(json.dumps(images,indent=2),encoding='utf-8')
    print(json.dumps({'enabled_shared_urls':len(urls),'usable_thumbnails':len(images),'bytes':sum((OUT/Path(i['src']).name).stat().st_size for i in images),'source':'enabled shared reference presets; read only'},ensure_ascii=False))
if __name__=='__main__':main()
