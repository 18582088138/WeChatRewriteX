from .test_team import scenario


def test_audio_project_role_file_review_and_revocation(tmp_path):
    scenario(tmp_path, """
import os,json
os.environ['WENSHU_FAKE_TTS']='1'
from app.core.models import DraftDoc,Block
from app.services import audio
aid=b.post('/api/articles',json={'title':'音频权限'}).json()['article']['id']
dao.save_workspace(DraftDoc(id=aid+'-v1',article_id=aid,version=1,blocks=[Block(id='one',type='paragraph',text='第一段科技资讯。'),Block(id='two',type='paragraph',text='第二段科技资讯。')]),'test')
db.execute('INSERT INTO project_members VALUES(?,?,1,1)',(aid,cm['id']))
base='/api/articles/'+aid+'/audio'
assert d.get(base).status_code==404
assert b.get('/api/audio/settings').status_code==403
profile=a.post('/api/audio/voices',json={'provider':'fake','voice_id':'fake','name':'测试','authorization':'测试授权','projects':[aid]}).json()
derived=b.post(base+'/derive',json={}).json()
assert derived['product']['revision']==1,derived
doc=derived['product']['doc'];doc['voice']['profile_id']=profile['id']
saved=b.put(base+'/speech',json={'revision':1,'doc':doc})
assert saved.status_code==200,saved.text
assert b.put(base+'/speech',json={'revision':1,'doc':doc}).status_code==409
assert d.get(base+'/history').status_code==404
assert b.get(base+'/history').status_code==200
assert b.post(base+'/generate',json={'revision':2,'voice_clone':True}).status_code==422
generated=b.post(base+'/generate',json={'revision':2})
assert generated.status_code==200,generated.text
bid=generated.json()['id']
token=team.actor.set(team.session(b.cookies.get('wenshu_member')))
op=team.operation.set((aid,'write'))
try: result=audio.run_batch(aid,{'batch_id':bid})
finally: team.operation.reset(op);team.actor.reset(token)
assert result['status']=='done',result
batch=b.get(base+'/batches/'+bid).json();fid=next(f['id'] for f in batch['files'] if f['name']=='audio.mp3')
url=base+'/files/'+fid
assert b.get(url).status_code==200
assert d.get(url).status_code==404
assert d.get(base+'/batches/'+bid).status_code==404
assert d.get(base+'/segments/'+b.get(base).json()['segments'][0]['url'].split('/')[-1]).status_code==404
script=b.post(base+'/reviews',json={'kind':'script','revision':2,'reviewer_id':bm['id']})
assert script.status_code==200,script.text
sid=script.json()['id']
assert b.put(base+'/reviews/'+sid,json={'status':'approved'}).status_code==200
sound=b.post(base+'/reviews',json={'kind':'audio','revision':2,'batch_id':bid,'reviewer_id':bm['id']})
assert sound.status_code==200,sound.text
assert b.put(base+'/reviews/'+sound.json()['id'],json={'status':'approved'}).status_code==200
assert b.post(base+'/export',json={'batch_id':bid}).status_code==404
export=c.post(base+'/export',json={'batch_id':bid})
assert export.status_code==200,export.text
assert b.get(base+'/exports/audio.mp3').status_code==200
assert b.get(export.json()['package_url']).status_code==200
assert d.get(export.json()['package_url']).status_code==404
# Voice scope can be withdrawn without deleting remote voices; historical audio remains governed by project ACL.
profile_body={'provider':'fake','voice_id':'fake','name':'测试','authorization':'测试授权','projects':[aid],'enabled':False}
assert a.put('/api/audio/voices/'+profile['id'],json=profile_body).status_code==200
assert b.post(base+'/generate',json={'revision':2}).status_code==422
assert b.get(base+'/batches/'+bid).json()['stale']
# Actual project removal blocks previously issued audio URLs.
db.execute('DELETE FROM project_members WHERE article_id=? AND member_id=?',(aid,cm['id']))
assert c.get(url).status_code==404
assert c.get(base+'/exports/audio.mp3').status_code==404
""", timeout=80)


def test_audio_self_review_policy_and_archived_write(tmp_path):
    scenario(tmp_path,"""
from app.core.models import DraftDoc,Block
aid=b.post('/api/articles',json={'title':'口播审核'}).json()['article']['id']
dao.save_workspace(DraftDoc(id=aid+'-v1',article_id=aid,version=1,blocks=[Block(id='p',type='paragraph',text='测试口播。')]),'test')
base='/api/articles/'+aid+'/audio'
assert b.post(base+'/derive',json={}).status_code==200
db.execute("UPDATE team_settings SET value='false' WHERE key='self_review'")
assert b.post(base+'/reviews',json={'kind':'script','revision':1,'reviewer_id':bm['id']}).status_code==403
assert b.post(base+'/reviews',json={'kind':'script','revision':1,'reviewer_id':dm['id']}).status_code==422
db.execute('UPDATE project_access SET archived=1 WHERE article_id=?',(aid,))
assert b.get(base).status_code==200
assert b.post(base+'/derive',json={'revision':1}).status_code==404
""")
