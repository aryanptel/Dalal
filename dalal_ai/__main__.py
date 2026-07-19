import os
import sys
import subprocess

def main():
    # Run streamlit on dalal_ai/ui/app.py
    ui_path = os.path.join(os.path.dirname(__file__), "ui", "app.py")
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", ui_path]))

if __name__ == "__main__":
    main()
