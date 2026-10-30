"""Cold Windows executable test in disposable runtime; only local HTTP and fixture data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import tempfile
import time
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();binary=Path(args.binary).resolve();output=Path(args.output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    version=subprocess.check_output([str(binary),'--version'],encoding='utf-8',timeout=30).strip()
    build=json.loads(subprocess.check_output([str(binary),'--build-info'],encoding='utf-8',timeout=30))
    assert build['version']=='1.1.0-rc.1',build
    with tempfile.TemporaryDirectory(prefix='wenshu-cold-exe-') as directory:
        runtime=Path(directory)/'runtime';runtime.mkdir()
        env=dict(os.environ)
        for key in list(env):
            if key.endswith(('_API_KEY','_SEARCH_KEY')) or key in ('APP_ACCESS_TOKEN','PYTHONPATH'):env[key]=''
        bootstrap=secrets.token_urlsafe(32)
        env.update(WENSHU_TEAM_MODE='1',WENSHU_BOOTSTRAP_TOKEN=bootstrap,WENSHU_MIN_FREE_MB='1',WENSHU_RUNTIME_DIR=str(runtime),WENSHU_DATA_DIR=str(runtime/'resource'),WENSHU_LOG_DIR=str(runtime/'log'))
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with (output/'exe-server.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(binary),'--runtime-dir',str(runtime),'--data-dir',str(runtime/'resource'),'--log-dir',str(runtime/'log'),'--host','127.0.0.1','--port',str(port),'--no-browser'],cwd=binary.parent,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                url=f'http://127.0.0.1:{port}'
                clients=[httpx.Client(base_url=url,timeout=20,trust_env=False) for _ in range(4)]
                a,b,c,d=clients
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Executable exited during startup; inspect exe-server.log')
                    try:
                        if a.get('/api/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.2)
                else:raise RuntimeError('Executable startup timed out')
                def check(response,status=200):
                    assert response.status_code==status,response.text
                    return response.json()
                check(a.post('/api/auth/bootstrap',json={'login':'admin','name':'Admin','password':'admin-password','token':bootstrap}))
                def login(client,name,password):
                    result=check(client.post('/api/auth/login',json={'login':name,'password':password}));client.headers['X-Wenshu-CSRF']=result['csrf']
                login(a,'admin','admin-password')
                members={}
                for client,name,role in ((b,'writer','member'),(c,'maintainer','maintainer'),(d,'outsider','member')):
                    members[name]=check(a.post('/api/auth/members',json={'login':name,'name':name,'password':name+'-password','role':role}))
                    login(client,name,name+'-password')
                    check(client.post('/api/auth/password',json={'old_password':name+'-password','password':name+'-changed-password'}))
                    login(client,name,name+'-changed-password')
                aid=check(b.post('/api/articles',json={'title':'Cold exe team flow','auto_collect':False}))['article']['id']
                def token(client):client.headers['X-Wenshu-Project-Revision']=client.get('/api/articles/'+aid).headers['X-Wenshu-Project-Revision']
                check(b.put('/api/articles/'+aid+'/access',json={'expected_revision':0,'owner_id':members['writer']['id'],'members':[{'member_id':members['maintainer']['id'],'can_create':True,'can_review':True}]}))
                token(b)
                check(b.post('/api/articles/'+aid+'/materials/upload-batch',files={'files':('source.md','冷启动执行包测试：独立账号、版本检查、固定人工快照与四平台发布包必须相互对应。'.encode(),'text/markdown')}))
                def wait_job(jid):
                    deadline=time.monotonic()+45
                    while time.monotonic()<deadline:
                        jobs=check(b.get('/api/jobs?article_id='+aid))['jobs'];job=next(j for j in jobs if j['id']==jid)
                        if job['status'] in ('done','failed'):
                            assert job['status']=='done',job;return
                        time.sleep(.2)
                    raise RuntimeError('Fixture job timed out')
                token(b);wait_job(check(b.post('/api/articles/'+aid+'/advance',json={'stage':'create'}))['job_id'])
                doc=check(b.get('/api/articles/'+aid+'/draft'))['draft']['doc']
                revision={'expected_version':doc['version'],'expected_revision':doc['edit_revision']}
                submitted=check(b.post('/api/articles/'+aid+'/human-review',json={'reviewer_id':members['maintainer']['id'],**revision}))
                check(c.put('/api/articles/'+aid+'/human-review/'+submitted['id'],json={'status':'approved','submission_revision':0,**revision}))
                token(c);check(c.post('/api/articles/'+aid+'/finalize',json={'force':True,**revision}))
                token(c);wait_job(check(c.post('/api/articles/'+aid+'/publish',json={'platforms':['wechat_mp','weibo','x','xhs']}))['job_id'])
                files=check(b.get('/api/articles/'+aid+'/exports'))['files'];assert files
                assert b.get('/files/'+files[0]).status_code==200
                assert d.get('/files/'+files[0]).status_code==404
                assert a.get('/files/app.db').status_code==404
                for client in clients:client.close()
            finally:
                process.terminate();process.wait(timeout=15)
        backup=Path(directory)/'backup';restored=Path(directory)/'restored'
        started=time.perf_counter()
        subprocess.run([str(binary),'--runtime-dir',str(runtime),'--data-dir',str(runtime/'resource'),'--backup',str(backup)],env=env,cwd=binary.parent,check=True,capture_output=True,timeout=45)
        backup_seconds=time.perf_counter()-started
        subprocess.run([str(binary),'--runtime-dir',str(restored),'--restore',str(backup)],env=env,cwd=binary.parent,check=True,capture_output=True,timeout=45)
        with sqlite3.connect(restored/'resource/app.db') as conn:
            assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert conn.execute('SELECT count(*) FROM members').fetchone()[0]==4
            assert conn.execute('SELECT count(*) FROM human_finalizations').fetchone()[0]==1
            assert conn.execute("SELECT count(*) FROM publish_jobs WHERE status='done'").fetchone()[0]==4
        report={'binary':str(binary),'version_output':version,'build':build,'members':4,'exports':len(files),'backup_seconds':round(backup_seconds,3),'scope':'cold local Windows executable; disposable runtime, not home host deployment'}
        (output/'exe-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Cold executable team flow and isolated CLI restore passed')


if __name__=='__main__':main()
