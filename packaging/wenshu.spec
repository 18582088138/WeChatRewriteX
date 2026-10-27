# PyInstaller 构建脚本：文枢 - 自媒体 Studio 单文件绿色执行包
# 用法（仓库根目录）：pyinstaller packaging/wenshu.spec
# 前置：python scripts/build_assets.py（生成 app/_assets）
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.getcwd())

datas = [(os.path.join(ROOT, "app", "_assets"), "wenshu_assets"),
         # 包内运行期数据文件（DB schema、卡片主题模板）
         (os.path.join(ROOT, "app", "storage", "schema.sql"), "app/storage"),
         (os.path.join(ROOT, "app", "services", "cards", "themes"),
          "app/services/cards/themes")]
hiddenimports = collect_submodules("app")
binaries = []

# uvicorn / playwright / trafilatura 等含动态导入与数据文件的依赖，整包收集。
# justext（trafilatura 正文抽取的停用词表 stoplists）、certifi（CA 根证书）、
# curl_cffi（yt-dlp 网络层的原生 DLL）漏收会在冻结态运行时炸：
# justext 缺 stoplists → WinError 3 找不到 _MEIxxx/justext/stoplists。
for pkg in ("uvicorn", "playwright", "trafilatura", "yt_dlp",
            "justext", "certifi", "curl_cffi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tests", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="文枢",
    debug=False,
    strip=False,
    upx=False,
    console=True,          # 服务端程序：保留控制台窗口显示日志
    disable_windowed_traceback=False,
    icon=None,
)
