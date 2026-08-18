import sys
import os
import subprocess
import traceback
from utils.paths import is_frozen, get_bundle_dir, get_logs_dir
from utils.logger import logger

def show_error_dialog(error_msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Dalal AI - Fatal Error", f"The application encountered a fatal error and must close.\n\n{error_msg}")
        root.destroy()
    except Exception:
        pass

def main():
    try:
        logger.info("Starting Dalal AI UI...")
        
        script_path = os.path.join(get_bundle_dir(), "dalal_ai", "ui", "app.py")
        
        if is_frozen():
            # Redirect stdout and stderr to log file since console=False hides them
            log_path = os.path.join(get_logs_dir(), "crash_log.txt")
            sys.stdout = open(log_path, 'w', encoding='utf-8')
            sys.stderr = sys.stdout

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
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.critical(f"Fatal error in run_ui.py: {error_msg}")
        if is_frozen():
            show_error_dialog(error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
