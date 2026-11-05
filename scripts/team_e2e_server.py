"""Disposable 20-topic migrated team fixture, no developer data or credentials."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='wenshu-team-e2e-') as directory:
        root=Path(directory)
        os.environ.update(WENSHU_RUNTIME_DIR=directory,WENSHU_DATA_DIR=str(root/'resource'),WENSHU_LOG_DIR=str(root/'log'),WENSHU_TEAM_MODE='0',WENSHU_MIN_FREE_MB='1',APP_ACCESS_TOKEN='')
        for key in list(os.environ):
            if key.endswith(('_API_KEY','_SEARCH_KEY')): os.environ[key]=''
        from app.storage import db,dao,library
        from app.core.models import DraftDoc,Block,ArticleStatus
        from app.services import team,draft_service
        db.init_db()
        topics=['开源模型','城市交通','家庭能源','跨城团队','教育工具','科学研究','健康资讯','文化阅读','软件质量','数据备份','隐私保护','手机应用','芯片制造','经济观察','环境保护','农业技术','宇宙探索','设计流程','知识整理','历史归档']
        projects=[dao.create_article('local://'+title,title=title) for title in topics]
        # Real legacy migration path: v3 -> account schema, no auto-public old common.
        library.ingest_text('Legacy common private evidence','旧公共库私有','common')
        os.environ['WENSHU_TEAM_MODE']='1';db.init_db()
        admin=team.initialize_admin('admin','管理员','admin-password')
        writer=team.create_member('writer','创作者','writer-password')
        reviewer=team.create_member('maintainer','维护负责人','maintainer-password','maintainer')
        outsider=team.create_member('outsider','其他成员','outsider-password')
        for index,project in enumerate(projects):
            aid=project['id']
            if index % 4 in (0,1):
                db.execute('UPDATE project_access SET owner_id=? WHERE article_id=?',(writer['id'],aid))
                db.execute('INSERT INTO project_members VALUES(?,?,1,1)',(aid,reviewer['id']))
            elif index % 4==2:
                db.execute('INSERT INTO project_members VALUES(?,?,1,1)',(aid,writer['id']))
                db.execute('INSERT INTO project_members VALUES(?,?,1,1)',(aid,outsider['id']))
            if index==19:db.execute('UPDATE project_access SET archived=1 WHERE article_id=?',(aid,))
            mid=library.ingest_text(f'{topics[index]}：固定验证资料，版本、素材与权限必须保留。',topics[index],'article',aid)
            doc=DraftDoc(id=aid+'-v0',article_id=aid,version=0,blocks=[Block(id='heading',type='heading',level=1,text=topics[index]),Block(id='paragraph',type='paragraph',text=f'{topics[index]}的初始正文，用于多人创作验收。',citations=[mid])])
            doc.meta.title_candidates=[topics[index]]
            draft_service.save_new_version(doc,'create');dao.set_article_status(aid,ArticleStatus.DRAFTED)
        import uvicorn
        from app.main import create_app
        uvicorn.run(create_app(),host='127.0.0.1',port=8013,log_level='warning')


if __name__=='__main__':main()
