"""Installed audio candidate: persistence, immutable exports and isolated restore."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


def main():
    base=Path(tempfile.mkdtemp(prefix='wenshu-v2-installed-'))
    runtime=base/'runtime';data=runtime/'resource'
    os.environ.update(WENSHU_RUNTIME_DIR=str(runtime),WENSHU_DATA_DIR=str(data),WENSHU_LOG_DIR=str(runtime/'logs'),WENSHU_TEAM_MODE='0',
                      WENSHU_FAKE_TTS='1',MINIMAX_DEFAULT_VOICE_ID='',APP_ACCESS_TOKEN='')
    for key in list(os.environ):
        if key.endswith(('_API_KEY','_SEARCH_KEY')):os.environ[key]=''
    from app import APP_VERSION
    from app.storage import db,dao
    from app.core.models import DraftDoc,Block
    from app.services import audio
    from app.services.audio_models import Derive,SpeechDoc,VoiceProfile,Generate,SubmitReview,ReviewAction
    from app.services.instance_backup import backup_instance,restore_instance
    from app.core import config
    db.init_db()
    aid=dao.create_article('',title='安装包音频验收')['id']
    dao.save_workspace(DraftDoc(id=aid+'-v1',article_id=aid,version=1,blocks=[Block(id='p',type='paragraph',text='安装包固定测试口播。此音频为离线测试音。')]),'test')
    state=audio.derive(aid,Derive())
    voice=audio.register_profile(VoiceProfile(provider='fake',voice_id='installed',name='安装包测试音',authorization='离线验证',projects=[aid]))
    doc=SpeechDoc.model_validate(state['product']['doc']);doc.voice.profile_id=voice['id']
    state=audio.save(aid,state['product']['revision'],doc)
    batch=audio.generate(aid,Generate(revision=state['product']['revision']))
    result=audio.run_batch(aid,{'batch_id':batch['id']})
    assert result['status']=='done',result
    script=audio.submit_review(aid,SubmitReview(kind='script',revision=state['product']['revision']))
    audio.decide_review(aid,script['id'],ReviewAction(status='approved'))
    review=audio.submit_review(aid,SubmitReview(kind='audio',revision=state['product']['revision'],batch_id=batch['id']))
    audio.decide_review(aid,review['id'],ReviewAction(status='approved'))
    exported=audio.export(aid,batch['id'])
    backup=base/'backup';restored=base/'restored'
    backup_instance(runtime,data,backup);restore_instance(backup,restored)
    conn=sqlite3.connect(restored/'resource/app.db')
    try:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT version FROM audio_schema').fetchone()[0]==1
        assert conn.execute('SELECT batch_id FROM audio_exports WHERE article_id=?',(aid,)).fetchone()[0]==batch['id']
        for path,sha in conn.execute('SELECT path,sha256 FROM audio_files WHERE article_id=?',(aid,)):
            assert audio.processing.checksum(restored/'resource/audio'/path)==sha
    finally:conn.close()
    assert (config.WEB_ROOT/'index.html').is_file()
    summary={'version':APP_VERSION,'audio_extension':1,'batch_id':batch['id'],'duration':audio.batch(aid,batch['id'])['result']['duration'],
             'backup_restore':'passed','calls':'FakeTTS only','real_requests':0,'clone_requests':0,
             'root':str(base),'package':str(Path(sys.modules['app'].__file__).resolve())}
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
