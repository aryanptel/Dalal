import sys
import os
import subprocess
import traceback

def main():
    print("=== Dalal AI Diagnostics ===")
    print(f"Python Version: {sys.version}")
    print(f"Current Directory: {os.getcwd()}")
    
    # 1. Test utils.paths
    try:
        from utils.paths import is_frozen, get_bundle_dir, get_user_data_dir
        print(f"\n[+] paths.py loaded.")
        print(f"  - is_frozen: {is_frozen()}")
        print(f"  - get_bundle_dir: {get_bundle_dir()}")
        print(f"  - get_user_data_dir: {get_user_data_dir()}")
    except Exception as e:
        print(f"[-] Failed to load utils.paths: {e}")
        traceback.print_exc()

    # 2. Test dependencies
    print("\n[+] Testing heavy dependencies exclusion...")
    try:
        import numpy
        print("  [-] numpy is still available.")
    except ImportError:
        print("  [+] numpy is successfully excluded/uninstalled.")
        
    try:
        import sklearn
        print("  [-] sklearn is still available.")
    except ImportError:
        print("  [+] sklearn is successfully excluded/uninstalled.")

    # 3. Test Playwright
    print("\n[+] Testing Playwright imports...")
    try:
        import playwright
        print("  [+] playwright loaded.")
    except ImportError:
        print("  [-] playwright not found!")

    # 4. Test Streamlit
    print("\n[+] Testing Streamlit imports...")
    try:
        import streamlit
        from streamlit.web import cli
        print("  [+] streamlit loaded.")
    except ImportError:
        print("  [-] streamlit not found!")

    # 5. Check UI app.py path
    app_path = os.path.join(get_bundle_dir(), "dalal_ai", "ui", "app.py") if 'get_bundle_dir' in locals() else None
    if app_path:
        print(f"\n[+] Checking Streamlit app path: {app_path}")
        if os.path.exists(app_path):
            print("  [+] App file exists.")
        else:
            print("  [-] App file NOT found! PyInstaller spec might be missing datas.")

if __name__ == '__main__':
    main()
