"""Run from an empty directory using a freshly installed wheel."""
import base64
import json
import os
from pathlib import Path
import sqlite3
import time


def main():
    os.environ['WENSHU_TEAM_MODE']='1'
    os.environ['WENSHU_RUNTIME_DIR']=str(Path('team-state').resolve())
    os.environ['WENSHU_DATA_DIR']=str(Path('team-state/resource').resolve())
    os.environ['WENSHU_LOG_DIR']=str(Path('team-state/log').resolve())
    for key in list(os.environ):
        if key.endswith(('_API_KEY','_SEARCH_KEY')):os.environ[key]=''
    import app
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.services import team,draft_service
    from app.storage import dao,db
    from app.core import config
    from app.core.models import DraftDoc,Block,ArticleStatus
    from app.services.instance_backup import backup_instance,restore_instance
    assert Path(app.__file__).resolve().parent != Path(__file__).resolve().parents[1]/'app', 'must use installed wheel'
    assert (Path(app.__file__).parent/'_assets/deployment/team.env.example').is_file()
    with TestClient(create_app()) as admin,TestClient(admin.app) as b,TestClient(admin.app) as c,TestClient(admin.app) as d:
        am=team.initialize_admin('admin','Admin','admin-password')
        bm=team.create_member('writer','Writer','writer-password')
        cm=team.create_member('maintainer','Maintainer','maintainer-password','maintainer')
        team.create_member('outsider','Outsider','outsider-password')
        for client,login,password in ((admin,'admin','admin-password'),(b,'writer','writer-password'),(c,'maintainer','maintainer-password'),(d,'outsider','outsider-password')):
            response=client.post('/api/auth/login',json={'login':login,'password':password});assert response.status_code==200,response.text
            client.headers['X-Wenshu-CSRF']=response.json()['csrf']
        p=b.post('/api/articles',json={'title':'Installed team smoke','auto_collect':False}).json()['article']['id']
        def token(client):
            client.headers['X-Wenshu-Project-Revision']=client.get('/api/articles/'+p).headers['X-Wenshu-Project-Revision']
        assert b.put('/api/articles/'+p+'/access',json={'expected_revision':0,'owner_id':bm['id'],'members':[{'member_id':cm['id'],'can_create':True,'can_review':True}]}).status_code==200
        token(b)
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jco8AAAAASUVORK5CYII=')
        upload=b.post('/api/articles/'+p+'/materials/upload',files={'file':('preview.png',png,'image/png')});assert upload.status_code==200,upload.text
        mid=upload.json()['material_id']
        assert b.get('/api/materials/'+mid+'/file').status_code==200
        assert d.get('/api/materials/'+mid+'/file').status_code==404
        doc=draft_service.save_new_version(DraftDoc(id=p+'-v0',article_id=p,version=0,blocks=[Block(id='h',type='heading',level=1,text='Installed team smoke'),Block(id='p',type='paragraph',text='Installed team explicit human approval.'),Block(id='i',type='image',asset_id=mid,caption='Approved image')]),'create')
        dao.set_article_status(p,ArticleStatus.DRAFTED)
        revision={'expected_version':doc.version,'expected_revision':doc.edit_revision}
        submitted=b.post('/api/articles/'+p+'/human-review',json={'reviewer_id':cm['id'],**revision});assert submitted.status_code==200,submitted.text
        sid=submitted.json()['id']
        decision=c.put('/api/articles/'+p+'/human-review/'+sid,json={'status':'approved','submission_revision':0,**revision});assert decision.status_code==200,decision.text
        token(c)
        final=c.post('/api/articles/'+p+'/finalize',json={'force':True,**revision});assert final.status_code==200,final.text
        token(c)
        exported=c.post('/api/articles/'+p+'/publish',json={'platforms':['wechat_mp','weibo','x','xhs']});assert exported.status_code==200,exported.text
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            job=db.query_one('SELECT status,error FROM jobs WHERE id=?',(exported.json()['job_id'],))
            if job['status'] in ('done','failed'):break
            time.sleep(.1)
        assert job['status']=='done',job
        files=b.get('/api/articles/'+p+'/exports').json()['files'];assert files
        assert b.get('/files/'+files[0]).status_code==200
        assert d.get('/files/'+files[0]).status_code==404
        assert b.get('/files/app.db').status_code==404
    backup=Path('team-backup').resolve();restored=Path('team-restored').resolve()
    start=time.perf_counter();backup_instance(config.RUNTIME_ROOT,config.data_dir(),backup);backup_seconds=time.perf_counter()-start
    start=time.perf_counter();restore_instance(backup,restored);restore_seconds=time.perf_counter()-start
    with sqlite3.connect(restored/'resource/app.db') as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT count(*) FROM members').fetchone()[0]==4
        assert conn.execute('SELECT submission_id FROM human_finalizations').fetchone()[0]==sid
        assert conn.execute("SELECT count(*) FROM publish_jobs WHERE status='done'").fetchone()[0]==4
    report={'version':app.APP_VERSION,'installed_app':str(Path(app.__file__).resolve()),'schema':6,'members':4,'approved_snapshot':p+'-v1','export_files':len(files),'backup_bytes':sum(f.stat().st_size for f in backup.rglob('*') if f.is_file()),'backup_seconds':round(backup_seconds,3),'restore_seconds':round(restore_seconds,3),'scope':'fresh wheel/local fixtures; not real host RTO'}
    Path('team-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Installed team wheel smoke passed: login, ACL, human approval, four exports and full restore')


if __name__=='__main__':main()
