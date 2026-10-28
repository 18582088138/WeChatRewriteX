"""Production app with disposable storage and no real API keys, for browser tests."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    with tempfile.TemporaryDirectory(prefix="wenshu-e2e-") as directory:
        os.environ["WENSHU_DATA_DIR"] = directory
        os.environ["WENSHU_LOG_DIR"] = str(Path(directory) / "logs")
        for key in ("DEEPSEEK_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                    "TAVILY_API_KEY", "BING_SEARCH_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY",
                    "COVERR_API_KEY", "MINIMAX_API_KEY", "MINIMAX_TTS_API_KEY", "APP_ACCESS_TOKEN"):
            os.environ[key] = ""
        import uvicorn
        from app.main import create_app
        uvicorn.run(create_app(), host="127.0.0.1", port=8011, log_level="warning")

if __name__ == "__main__":
    main()
