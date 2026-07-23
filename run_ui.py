import sys
import os
import subprocess
from utils.paths import is_frozen, get_bundle_dir
from utils.logger import logger

def main():
    logger.info("Starting Dalal AI UI...")
    
    script_path = os.path.join(get_bundle_dir(), "dalal_ai", "ui", "app.py")
    
    if is_frozen():
        from streamlit.web import cli as stcli
        
        # Override sys.argv to emulate running `streamlit run dalal_ai/ui/app.py`
        sys.argv = [
            "streamlit",
            "run",
            script_path,
            "--global.developmentMode=false",
            "--server.headless=false"
        ]
        
        logger.info(f"Running Streamlit via PyInstaller bundle: {sys.argv}")
        sys.exit(stcli.main())
    else:
        logger.info("Running Streamlit from source via subprocess...")
        subprocess.run([sys.executable, "-m", "streamlit", "run", script_path])

if __name__ == "__main__":
    main()
