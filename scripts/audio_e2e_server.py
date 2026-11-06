"""Disposable audio browser fixture. No live credentials or user data."""
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='wenshu-audio-browser-') as directory:
        os.environ.update(WENSHU_RUNTIME_DIR=directory,WENSHU_DATA_DIR=str(Path(directory)/'resource'),
                          WENSHU_LOG_DIR=str(Path(directory)/'logs'),WENSHU_TEAM_MODE='0',WENSHU_FAKE_TTS='1',
                          MINIMAX_DEFAULT_VOICE_ID='',APP_ACCESS_TOKEN='')
        for key in list(os.environ):
            if key.endswith(('_API_KEY','_SEARCH_KEY')):os.environ[key]=''
        from app.storage import db,dao
        from app.core.models import DraftDoc,Block,ArticleStatus
        from app.services import audio
        from app.services.audio_models import VoiceProfile
        db.init_db()
        aid=dao.create_article('',title='音频固定测试主题')['id']
        doc=DraftDoc(id=aid+'-v1',article_id=aid,version=1,blocks=[Block(id='b1',type='paragraph',text='2026年11月5日，模型运行速度提高12.5%。'),Block(id='b2',type='paragraph',text='AI 芯片配置32GB内存。事实和来源需要人工核对。')])
        dao.save_workspace(doc,'test');dao.set_article_status(aid,ArticleStatus.DRAFTED)
        audio.register_profile(VoiceProfile(provider='fake',voice_id='fixture',name='离线测试音',authorization='只用于浏览器测试',projects=[aid]))
        import uvicorn
        from app.main import create_app
        uvicorn.run(create_app(),host='127.0.0.1',port=8015,log_level='warning')


if __name__=='__main__':main()
