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
import sys,traceback
sys.excepthook=lambda *args: traceback.print_exception(*args,file=sys.__stdout__)
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
import re
for client in (a,b,c,d):
    original = client.request
    def guarded(method,url,*,_original=original,**kwargs):
        headers=dict(kwargs.pop('headers',{}) or {})
        if method.upper() not in ('GET','HEAD','OPTIONS') and 'X-Wenshu-Project-Revision' not in headers:
            match=re.search('/api/articles/([^/]+)',str(url)); aid=match.group(1) if match else None
            if not aid:
                match=re.search('/api/(drafts|materials|review-items)/([^/]+)',str(url))
                if match:
                    kind,oid=match.groups()
                    if kind=='materials':
                        m=dao.get_material(oid);aid=m['article_id'] if m else None
                        aid=(kwargs.get('json') or {}).get('article_id',aid)
                    elif kind=='drafts': aid=oid.rsplit('-v',1)[0]
            row=db.query_one('SELECT revision FROM project_access WHERE article_id=?',(aid,)) if aid else None
            if row:headers['X-Wenshu-Project-Revision']=str(row['revision'])
        return _original(method,url,headers=headers,**kwargs)
    client.request=guarded
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
    logs = tmp_path / "logs" / "wenshu.log"
    assert result.returncode == 0, result.stdout + result.stderr + (logs.read_text(encoding="utf-8")[-4000:] if logs.exists() else "")


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
assert db.query_one('PRAGMA user_version')['user_version'] == 6
db.init_db()
assert db.query_one('PRAGMA user_version')['user_version'] == 6
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


def test_membership_transfer_archive_sharing_and_owned_copy(tmp_path):
    scenario(tmp_path, """
p = b.post('/api/articles',json={'title':'P1','auto_collect':False}).json()['article']['id']
q = d.post('/api/articles',json={'title':'P2','auto_collect':False}).json()['article']['id']
access=b.get('/api/articles/'+p+'/access').json()
body={'expected_revision':access['revision'],'owner_id':bm['id'],'members':[{'member_id':cm['id'],'can_review':True}]}
assert b.put('/api/articles/'+p+'/access',json=body).status_code==200
assert b.put('/api/articles/'+p+'/access',json=body).status_code==409
assert c.get('/api/articles/'+p).status_code==200
assert c.get('/api/articles/'+q).status_code==404
assert d.get('/api/articles/'+p).status_code==404
assert c.put('/api/articles/'+p+'/selection',json={'material_ids':[]}).status_code==404
mid=a.post('/api/materials/upload',files={'file':('shared.md',b'shared text','text/markdown')}).json()['material_id']
assert b.get('/api/materials/'+mid+'/text').status_code==404
assert a.put('/api/materials/'+mid+'/sharing',json={'shared':True}).status_code==200
assert b.get('/api/materials/'+mid+'/file').status_code==200
copied=b.post('/api/materials/'+mid+'/copy-to-article',json={'article_id':p})
assert copied.status_code==200,copied.text
dest=dao.get_material(copied.json()['material_id']); source=dao.get_material(mid)
assert dest['path'] != source['path'] and dest['source_material_id']==mid
assert a.put('/api/materials/'+mid+'/sharing',json={'shared':False}).status_code==200
assert b.get('/files/'+source['path']).status_code==404
assert b.get('/files/'+dest['path']).status_code==200
body.update(expected_revision=b.get('/api/articles/'+p+'/access').json()['revision'],owner_id=cm['id'],archived=True,members=[])
assert b.put('/api/articles/'+p+'/access',json=body).status_code==200
assert b.get('/api/articles/'+p).status_code==404
assert c.get('/api/articles/'+p).status_code==200
assert c.put('/api/articles/'+p+'/selection',json={'material_ids':[]}).status_code==404
assert a.put('/api/auth/members/'+cm['id'],json={'role':'maintainer','enabled':False}).status_code==409
assert db.query_one("SELECT count(*) AS n FROM audit_events WHERE article_id=? AND action='project.access'",(p,))['n']==2
db.init_db(); assert db.query_one('SELECT count(*) AS n FROM project_access')['n']==2
""")


def test_human_return_revision_approval_finalization_and_export(tmp_path):
    scenario(tmp_path, """
from app.core.models import DraftDoc,Block,ArticleStatus
from app.services import draft_service
p=b.post('/api/articles',json={'title':'human-flow','auto_collect':False}).json()['article']['id']
acl=b.get('/api/articles/'+p+'/access').json()
assert b.put('/api/articles/'+p+'/access',json={'expected_revision':0,'owner_id':bm['id'],'members':[{'member_id':cm['id'],'can_create':True,'can_review':True}]}).status_code==200
doc=draft_service.save_new_version(DraftDoc(id=p+'-v0',article_id=p,version=0,blocks=[Block(id='h',type='heading',level=1,text='Human flow'),Block(id='b',type='paragraph',text='First draft')]),'create')
dao.set_article_status(p,ArticleStatus.DRAFTED)
def rev():
    current=b.get('/api/articles/'+p+'/draft').json()['draft']['doc']
    return {'expected_version':current['version'],'expected_revision':current['edit_revision']}
def submit():
    r=b.post('/api/articles/'+p+'/human-review',json={'reviewer_id':cm['id'],**rev()}); assert r.status_code==200,r.text; return r.json()
def decide(client,s,status,reason=''):
    return client.put('/api/articles/'+p+'/human-review/'+s['id'],json={'status':status,'reason':reason,'submission_revision':s['revision'],**rev()})
s=submit(); assert submit()['id']==s['id']
assert d.put('/api/articles/'+p+'/human-review/'+s['id'],json={'status':'approved','submission_revision':0,**rev()}).status_code==404
assert decide(b,s,'approved').status_code==403
co=c.post('/api/articles/'+p+'/human-review/'+s['id']+'/comments',json={'anchor':'b','message':'Improve clarity'})
assert co.status_code==200,co.text
assert decide(c,s,'returned','Please revise').status_code==200
edited=b.put('/api/drafts/'+p+'-v1/edit',json={'expected_revision':rev()['expected_revision'],'ops':[{'op':'update','block_id':'b','text':'Revised draft'}]})
assert edited.status_code==200,edited.text
s=submit(); assert decide(c,s,'approved').status_code==200
assert b.get('/api/articles/'+p+'/human-review').json()['valid_approval']
# Discussion state never mutates the content token or the approval.
assert b.put('/api/articles/'+p+'/human-review/'+s['id']+'/comments/'+co.json()['id'],json={'status':'resolved','expected_revision':0}).status_code==404
assert b.post('/api/articles/'+p+'/finalize',json={'force':True,**rev()}).status_code==404
final=c.post('/api/articles/'+p+'/finalize',json={'force':True,**rev()})
assert final.status_code==200,final.text
assert db.query_one('SELECT submission_id FROM human_finalizations WHERE snapshot_id=?',(p+'-v1',))['submission_id']==s['id']
export=c.post('/api/articles/'+p+'/publish',json={'platforms':['weibo']})
assert export.status_code==200,export.text
assert b.post('/api/articles/'+p+'/publish',json={'platforms':['weibo']}).status_code==404
assert b.put('/api/drafts/'+p+'-v1/edit',json={'expected_revision':rev()['expected_revision'],'ops':[{'op':'update','block_id':'b','text':'New version'}]}).status_code==200
assert not b.get('/api/articles/'+p+'/human-review').json()['valid_approval']
assert c.post('/api/articles/'+p+'/finalize',json={'force':True,**rev()}).status_code==409
s=submit(); old=rev()
assert b.put('/api/drafts/'+p+'-v2/edit',json={'expected_revision':old['expected_revision'],'ops':[{'op':'update','block_id':'b','text':'Late edit'}]}).status_code==200
assert decide(c,s,'approved').status_code==409
assert a.post('/api/articles/'+p+'/finalize',json={'force':True,'exception_reason':'Emergency documented release',**rev()}).status_code==200
""")


def test_human_self_review_setting_material_change_and_comment_state(tmp_path):
    scenario(tmp_path, """
from app.core.models import DraftDoc,Block,ArticleStatus
from app.services import draft_service
p=b.post('/api/articles',json={'title':'self-review','auto_collect':False}).json()['article']['id']
mid=b.post('/api/articles/'+p+'/materials/upload-batch',files={'files':('source.md',b'evidence','text/markdown')}).json()['ok'][0]['material_id']
doc=draft_service.save_new_version(DraftDoc(id=p+'-v0',article_id=p,version=0,blocks=[Block(id='b',type='paragraph',text='test',citations=[mid])]),'create');dao.set_article_status(p,ArticleStatus.DRAFTED)
r={'expected_version':1,'expected_revision':doc.edit_revision}
s=b.post('/api/articles/'+p+'/human-review',json={'reviewer_id':bm['id'],**r}).json()
comment=b.post('/api/articles/'+p+'/human-review/'+s['id']+'/comments',json={'message':'self comment'}).json()
assert b.put('/api/articles/'+p+'/human-review/'+s['id'],json={'status':'approved','submission_revision':0,**r}).status_code==200
assert b.put('/api/articles/'+p+'/human-review/'+s['id']+'/comments/'+comment['id'],json={'status':'resolved','expected_revision':0}).status_code==200
assert b.get('/api/articles/'+p+'/human-review').json()['valid_approval']
assert a.put('/api/team/settings',json={'self_review':False}).status_code==200
assert b.post('/api/articles/'+p+'/human-review',json={'reviewer_id':bm['id'],**r}).status_code==403
# Material metadata is part of approval, including citations.
assert b.patch('/api/materials/'+mid,json={'title':'new evidence title'}).status_code==200
assert not b.get('/api/articles/'+p+'/human-review').json()['valid_approval']
assert b.put('/api/team/settings',json={'self_review':True}).status_code==403
""")


def test_concurrent_guards_late_ai_revocation_and_expiring_lease(tmp_path):
    scenario(tmp_path, """
import threading,time
from app.core.models import DraftDoc,Block,ArticleStatus
from app.services import draft_service
from app.agents.creator import CreatorAgent
p=b.post('/api/articles',json={'title':'race','auto_collect':False}).json()['article']['id']
assert b.put('/api/articles/'+p+'/access',json={'expected_revision':0,'owner_id':bm['id'],'members':[{'member_id':cm['id'],'can_create':True,'can_review':True}]}).status_code==200
doc=draft_service.save_new_version(DraftDoc(id=p+'-v0',article_id=p,version=0,blocks=[Block(id='b',type='paragraph',text='Original')]),'create');dao.set_article_status(p,ArticleStatus.DRAFTED)
token=b.get('/api/articles/'+p).headers['X-Wenshu-Project-Revision']
body={'expected_revision':doc.edit_revision,'ops':[{'op':'update','block_id':'b','text':'B saved'}]}
assert b.put('/api/drafts/'+p+'-v1/edit',json=body,headers={'X-Wenshu-Project-Revision':token}).status_code==200
body['ops'][0]['text']='C local input'
assert c.put('/api/drafts/'+p+'-v1/edit',json=body,headers={'X-Wenshu-Project-Revision':token}).status_code==409
assert c.put('/api/drafts/'+p+'-v1/edit',json=body,headers={'X-Wenshu-Project-Revision':''}).status_code==428
assert draft_service.get_doc(p)[0].blocks[0].text=='B saved'
def revision(): return draft_service.get_doc(p)[0].edit_revision
started=threading.Event();release=threading.Event()
CreatorAgent.llm_available=lambda self:True
def fake(self,aid,new,bids,instruction):
    started.set();assert release.wait(10);new.blocks[0].text='Late AI';return new
CreatorAgent.regenerate_blocks=fake
out=[]
t=threading.Thread(target=lambda:out.append(c.post('/api/drafts/'+p+'-v1/regenerate',json={'expected_revision':revision(),'block_ids':['b']})))
t.start();assert started.wait(10)
assert b.put('/api/drafts/'+p+'-v1/edit',json={'expected_revision':revision(),'ops':[{'op':'update','block_id':'b','text':'Human wins'}]}).status_code==200
release.set();t.join(10);assert out[0].status_code==409,out[0].text
assert draft_service.get_doc(p)[0].blocks[0].text=='Human wins'
started.clear();release.clear();out.clear()
t=threading.Thread(target=lambda:out.append(c.post('/api/drafts/'+p+'-v1/regenerate',json={'expected_revision':revision(),'block_ids':['b']})))
t.start();assert started.wait(10)
access=b.get('/api/articles/'+p+'/access').json()
assert b.put('/api/articles/'+p+'/access',json={'expected_revision':access['revision'],'owner_id':bm['id'],'members':[]}).status_code==200
release.set();t.join(10);assert out[0].status_code==404,out[0].text
assert draft_service.get_doc(p)[0].blocks[0].text=='Human wins'
lease=b.post('/api/articles/'+p+'/lease',json={'client_id':'browser-one'});assert lease.json()['acquired']
assert not b.post('/api/articles/'+p+'/lease',json={'client_id':'browser-two'}).json()['acquired']
db.execute('UPDATE edit_leases SET expires=?',(time.time()-1,))
assert b.post('/api/articles/'+p+'/lease',json={'client_id':'browser-two'}).json()['acquired']
assert d.get('/api/articles/'+p+'/audit').status_code==404
assert b.get('/api/team/audit').status_code==403
assert b.get('/api/team/work').status_code==200
audit=b.get('/api/articles/'+p+'/audit').text
assert 'password_hash' not in audit and 'csrf' not in audit and 'writer-password' not in audit
""")
