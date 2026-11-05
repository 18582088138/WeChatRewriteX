"""Use actual v1.0 sources to seed data, migrate a copy and restore old data with old code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'build/s7-validation';output.mkdir(parents=True,exist_ok=True)
    archive=output/'v1.0-source.zip'
    subprocess.run(['git','archive','--format=zip','v1.0','-o',str(archive)],cwd=ROOT,check=True)
    with tempfile.TemporaryDirectory(prefix='wenshu-upgrade-') as directory:
        root=Path(directory);old_source=root/'old-source';old_source.mkdir()
        with zipfile.ZipFile(archive) as bundle:bundle.extractall(old_source)
        old_data=root/'old-data'
        def run(source,runtime,data,code,mode):
            env=dict(os.environ)
            for key in list(env):
                if key.endswith(('_API_KEY','_SEARCH_KEY')):env[key]=''
            env.update(WENSHU_TEAM_MODE=mode,WENSHU_RUNTIME_DIR=str(runtime),WENSHU_DATA_DIR=str(data),WENSHU_LOG_DIR=str(root/'log'),APP_ACCESS_TOKEN='',PYTHONPATH=str(source))
            result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=source,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
            assert result.returncode==0,result.stdout+result.stderr
            return result.stdout
        old=run(old_source,old_source,old_data,"""
import json
from fastapi.testclient import TestClient
from app.main import create_app
from app.storage import dao,library,db
from app.core.models import DraftDoc,Block,ArticleStatus
from app.services import draft_service,workflow
with TestClient(create_app(start_worker=False)) as client:
    aid=dao.create_article('local://old','Legacy preserved project')['id']
    mid=library.ingest_text('Preserved old source','Old source','article',aid)
    doc=draft_service.save_new_version(DraftDoc(id=aid+'-v0',article_id=aid,version=0,blocks=[Block(id='p',type='paragraph',text='Legacy final body',citations=[mid])]),'create')
    dao.set_article_status(aid,ArticleStatus.DRAFTED);workflow.finalize(aid,force=True)
    from app.services.publish.exporter import export_variants
    assert export_variants(aid,['weibo'])['ok']
    assert db.query_one('PRAGMA user_version')['user_version']==3
    print(json.dumps({'aid':aid,'mid':mid,'doc':draft_service.get_doc(aid)[0].model_dump()}))
""",'0')
        fixture=json.loads(old.strip().splitlines()[-1]);fixture_file=root/'fixture.json';fixture_file.write_text(json.dumps(fixture),encoding='utf-8')
        backup=root/'before-upgrade';upgrade=root/'upgrade';rollback=root/'rollback'
        run(ROOT,root/'current-maintenance',old_data,f"""
from pathlib import Path
from app.services.instance_backup import backup_instance,restore_instance
backup_instance(Path({str(old_source)!r}),Path({str(old_data)!r}),Path({str(backup)!r}))
restore_instance(Path({str(backup)!r}),Path({str(upgrade)!r}))
restore_instance(Path({str(backup)!r}),Path({str(rollback)!r}))
""",'0')
        run(ROOT,upgrade,upgrade/'resource',f"""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.storage import db,dao
from app.services import team,draft_service
f=json.loads(Path({str(fixture_file)!r}).read_text());aid=f['aid']
with TestClient(create_app(start_worker=False)) as client:
    admin=team.initialize_admin('admin','Admin','admin-password')
    logged=client.post('/api/auth/login',json={{'login':'admin','password':'admin-password'}}).json();client.headers['X-Wenshu-CSRF']=logged['csrf']
    assert db.query_one('PRAGMA user_version')['user_version']==6
    assert draft_service.get_doc(aid)[0].model_dump()==f['doc']
    assert client.get('/api/materials/'+f['mid']+'/file').status_code==200
    head=client.get('/api/articles/'+aid);client.headers['X-Wenshu-Project-Revision']=head.headers['X-Wenshu-Project-Revision']
    assert client.post('/api/articles/'+aid+'/publish',json={{'platforms':['weibo']}}).status_code==409
    doc=f['doc'];result=client.post('/api/articles/'+aid+'/finalize',json={{'expected_version':doc['version'],'expected_revision':doc['edit_revision'],'exception_reason':'Verified legacy snapshot exception'}})
    assert result.status_code==200,result.text
    db.init_db();assert db.query_one('SELECT count(*) AS n FROM members')['n']==1
    assert db.query_one('SELECT count(*) AS n FROM project_access')['n']==1
""",'1')
        run(old_source,old_source,rollback/'resource',f"""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.storage import db
from app.services import draft_service
f=json.loads(Path({str(fixture_file)!r}).read_text());aid=f['aid']
with TestClient(create_app(start_worker=False)) as client:
    assert db.query_one('PRAGMA user_version')['user_version']==3
    assert draft_service.get_doc(aid)[0].model_dump()==f['doc']
    assert client.get('/api/materials/'+f['mid']+'/file').status_code==200
    files=client.get('/api/articles/'+aid+'/exports').json()['files'];assert files
    assert client.get('/files/'+files[0]).status_code==200
""",'0')
        report={'baseline':subprocess.check_output(['git','rev-parse','v1.0^{commit}'],cwd=ROOT,text=True).strip(),'old_schema':3,'new_schema':6,'backup_bytes':sum(p.stat().st_size for p in backup.rglob('*') if p.is_file()),'validated':'actual v1.0 code -> full backup -> team migration -> full backup rollback with v1.0 code','scope':'isolated synthetic fixture; no real user data'}
        (output/'upgrade-rollback.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Actual v1.0 upgrade and complete-backup rollback smoke passed')


if __name__=='__main__':main()
