"""Team tests run in isolated processes so legacy-mode regression remains independent."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIX = """
from contextlib import ExitStack
from fastapi.testclient import TestClient
from app.main import create_app
from app.storage import db, dao
from app.services import team
stack = ExitStack()
a = stack.enter_context(TestClient(create_app(start_worker=False)))
admin = team.initialize_admin('admin', '管理员', 'admin-password')
b = stack.enter_context(TestClient(a.app))
c = stack.enter_context(TestClient(a.app))
d = stack.enter_context(TestClient(a.app))
bm = team.create_member('writer','创作者','writer-password')
cm = team.create_member('maintainer','维护负责人','maintainer-password','maintainer')
dm = team.create_member('outsider','无权成员','outsider-password')
def sign(client, login, password):
    result = client.post('/api/auth/login',json={'login':login,'password':password})
    assert result.status_code == 200, result.text
    client.headers['X-Wenshu-CSRF'] = result.json()['csrf']
sign(a,'admin','admin-password'); sign(b,'writer','writer-password'); sign(c,'maintainer','maintainer-password'); sign(d,'outsider','outsider-password')
"""


def scenario(tmp_path, code):
    env = dict(os.environ)
    env.update(WENSHU_TEAM_MODE="1", WENSHU_RUNTIME_DIR=str(tmp_path), WENSHU_DATA_DIR=str(tmp_path / "resource"),
               WENSHU_LOG_DIR=str(tmp_path / "logs"), APP_ACCESS_TOKEN="", WENSHU_BOOTSTRAP_TOKEN="x"*32)
    for key in list(env):
        if key.endswith(("_API_KEY", "_SEARCH_KEY")):
            env[key] = ""
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", PREFIX + code + "\nstack.close()"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_member_sessions_csrf_and_last_administrator(tmp_path):
    scenario(tmp_path, """
anonymous = TestClient(a.app)
assert anonymous.get('/api/articles').status_code == 401
assert anonymous.get('/api/articles',headers={'Authorization':'Bearer shared-token'}).status_code == 401
assert b.get('/api/settings').status_code == 403
assert b.post('/api/auth/members',json={'login':'evil','name':'evil','password':'evil-password'}).status_code == 403
saved = b.headers.pop('X-Wenshu-CSRF')
assert b.post('/api/articles',json={'title':'csrf'}).status_code == 403
b.headers['X-Wenshu-CSRF'] = saved
assert b.post('/api/articles',json={'title':'origin'},headers={'Origin':'https://evil.example'}).status_code == 403
assert a.put('/api/auth/members/'+admin['id'],json={'role':'member','enabled':True}).status_code == 409
assert b.post('/api/auth/logout').status_code == 200
assert b.get('/api/articles').status_code == 401
sign(b,'writer','writer-password')
assert a.put('/api/auth/members/'+bm['id'],json={'role':'member','enabled':False}).status_code == 200
assert b.get('/api/articles').status_code == 401
assert db.query_one('SELECT password_hash FROM members WHERE id=?',(bm['id'],))['password_hash'].startswith('scrypt$')
assert 'writer-password' not in a.get('/api/auth/members').text
""")


def test_project_lists_files_and_foreign_material_ids_are_protected(tmp_path):
    scenario(tmp_path, """
p = b.post('/api/articles',json={'title':'private-keyword','auto_collect':False}).json()['article']['id']
upload = b.post('/api/articles/'+p+'/materials/upload-batch',files={'files':('source.md',b'private evidence','text/markdown')})
assert upload.status_code == 200, upload.text
mid = upload.json()['ok'][0]['material_id']
material = dao.get_material(mid)
assert d.get('/api/articles/'+p).status_code == 404
assert d.get('/api/articles?q=private-keyword').json()['total'] == 0
assert d.get('/api/materials/'+mid+'/text').status_code == 404
assert d.get('/files/'+material['path']).status_code == 404
assert b.get('/files/'+material['path']).status_code == 200
db.execute('INSERT INTO project_members VALUES(?,?,1,1)',(p,cm['id']))
assert c.get('/api/articles/'+p).status_code == 200
q = d.post('/api/articles',json={'title':'other','auto_collect':False}).json()['article']['id']
assert d.put('/api/articles/'+q+'/selection',json={'material_ids':[mid]}).status_code == 404
db.execute('DELETE FROM project_members WHERE article_id=? AND member_id=?',(p,cm['id']))
assert c.get('/files/'+material['path']).status_code == 404
assert b.post('/api/articles/'+p+'/finalize',json={}).status_code == 404
assert db.query_one('PRAGMA user_version')['user_version'] == 4
db.init_db()
assert db.query_one('PRAGMA user_version')['user_version'] == 4
""")


def test_team_worker_records_member_and_runs_authorized_generation(tmp_path):
    scenario(tmp_path, """
import time
worker_app = stack.enter_context(TestClient(create_app(start_worker=True)))
p = b.post('/api/articles',json={'title':'authorized generation','auto_collect':False}).json()['article']['id']
assert b.post('/api/articles/'+p+'/materials/upload-batch',files={'files':('source.md',b'authorized source content','text/markdown')}).status_code == 200
job = b.post('/api/articles/'+p+'/advance',json={'stage':'create'})
assert job.status_code == 200, job.text
deadline = time.monotonic()+20
while time.monotonic()<deadline:
    row = db.query_one('SELECT * FROM jobs WHERE id=?',(job.json()['job_id'],))
    if row['status'] in ('done','failed'): break
    time.sleep(.1)
assert row['status']=='done', row
assert __import__('json').loads(row['payload_json'])['_member_id']==bm['id']
assert d.get('/api/jobs?article_id='+p).status_code == 404
assert d.get('/api/jobs').json()['jobs'] == []
assert 'payload_json' not in b.get('/api/jobs?article_id='+p).text
""")

