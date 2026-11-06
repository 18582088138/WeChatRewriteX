"""Exercise a newly built Windows executable through real local HTTP."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);parser.add_argument('--report',required=True)
    args=parser.parse_args()
    exe=Path(args.exe).resolve()
    built=json.loads(subprocess.check_output([str(exe),'--build-info'],encoding='utf-8',timeout=20))
    with socket.socket() as socket_probe:
        socket_probe.bind(('127.0.0.1',0));port=socket_probe.getsockname()[1]
    base=Path(tempfile.mkdtemp(prefix='wenshu-v2-exe-'));runtime=base/'runtime';runtime.mkdir()
    env=dict(os.environ)
    env.update(WENSHU_FAKE_TTS='1',MINIMAX_DEFAULT_VOICE_ID='',APP_ACCESS_TOKEN='',WENSHU_TEAM_MODE='0',
               WENSHU_FFMPEG=shutil.which('ffmpeg') or '',WENSHU_FFPROBE=shutil.which('ffprobe') or '')
    for key in list(env):
        if key.endswith(('_API_KEY','_SEARCH_KEY')):env[key]=''
    log=(base/'process.log').open('wb')
    kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    process=subprocess.Popen([str(exe),'--runtime-dir',str(runtime),'--data-dir',str(runtime/'resource'),
                              '--log-dir',str(base/'logs'),'--host','127.0.0.1','--port',str(port),'--no-browser'],
                             cwd=base,env=env,stdout=log,stderr=subprocess.STDOUT,**kwargs)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=40) as client:
            def call(method,path,**kwargs):
                response=client.request(method,path,**kwargs)
                assert response.status_code==200,(path,response.status_code,response.text[:500])
                return response.json()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Executable exited; inspect isolated process.log')
                try:
                    if client.get('/api/ready').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.25)
            else:raise RuntimeError('Executable readiness timeout')
            assert client.get('/').status_code==200
            aid=call('POST','/api/articles',json={'title':'Windows音频候选验证'})['article']['id']
            upload=call('POST',f'/api/articles/{aid}/materials/upload-batch',files={'files':('source.txt','科技新闻固定素材。模型运行效率提高12.5%。保留来源并人工审核。'.encode(),'text/plain')})
            created=call('POST',f'/api/articles/{aid}/advance',json={'stage':'create','selected_material_ids':[upload['ok'][0]['material_id']]})
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                jobs=call('GET',f'/api/jobs?article_id={aid}')['jobs']
                job=next((j for j in jobs if j['id']==created['job_id']),None)
                if job and job['status']=='done':break
                if job and job['status']=='failed':raise AssertionError(job['error'])
                time.sleep(.2)
            audio_base=f'/api/articles/{aid}/audio'
            state=call('POST',audio_base+'/derive',json={})
            profile=call('POST','/api/audio/voices',json={'provider':'fake','voice_id':'windows-fixture','name':'测试音','authorization':'仅离线验证','projects':[aid]})
            doc=state['product']['doc'];doc['voice']['profile_id']=profile['id']
            state=call('PUT',audio_base+'/speech',json={'revision':state['product']['revision'],'doc':doc})
            bid=call('POST',audio_base+'/generate',json={'revision':state['product']['revision']})['id']
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                batch=call('GET',audio_base+'/batches/'+bid)
                if batch['status']=='done':break
                if batch['status'] in ('failed','unknown'):raise AssertionError(batch['error'])
                time.sleep(.3)
            assert batch['status']=='done',batch
            for kind in ('script','audio'):
                review=call('POST',audio_base+'/reviews',json={'kind':kind,'revision':state['product']['revision'],'batch_id':bid if kind=='audio' else None})
                call('PUT',audio_base+'/reviews/'+review['id'],json={'status':'approved'})
            exported=call('POST',audio_base+'/export',json={'batch_id':bid})
            assert client.get(exported['package_url']).status_code==200
            assert client.get(audio_base+'/exports/audio.mp3').status_code==200
            assert client.get('/files/app.db').status_code==404
            report={'exe':str(exe),'root':str(base),'status':'passed','version':built['version'],'build_commit':built['commit'],
                    'batch_id':bid,'duration':batch['result']['duration'],'fake_only':True,'real_requests':0,'clone_requests':0,
                    'checks':['independent runtime','current frontend','draft derive','TTS worker','local tools','approval','ZIP/MP3 HTTP download','file boundary']}
            output=Path(args.report);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
    finally:
        process.terminate()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()


if __name__=='__main__':main()
