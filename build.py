import os
import sys
import shutil
import subprocess

if sys.platform == "win32":
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream)
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

def clean():
    print("🧹 Cleaning previous builds...")
    for folder in ["build", "dist", "release"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"Removed {folder}/")
    os.makedirs("release", exist_ok=True)

def check_dependencies():
    print("📦 Installing/verifying dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "pyinstaller"], check=True)

def build_exe():
    print("🔨 Building PyInstaller executable...")
    # Run PyInstaller with the spec file
    subprocess.run([sys.executable, "-m", "PyInstaller", "DalalAI.spec", "--clean", "--noconfirm"], check=True)

def _dist_root():
    """
    Locate the one-folder output.

    PyInstaller 6 puts everything except the launcher under ``_internal``;
    PyInstaller 5 puts it beside the launcher.  Return (app_dir, payload_dir).
    """
    app_dir = os.path.join("dist", "DalalAI")
    internal = os.path.join(app_dir, "_internal")
    return app_dir, (internal if os.path.isdir(internal) else app_dir)


def verify_build():
    """
    Fail the build if the frozen app is missing something it needs at runtime.

    This exists because of a real shipped bug: `dalal_ai/` and `utils/` were
    packaged as *data* only, so PyInstaller never parsed them and `pyperclip`
    — imported solely inside `browser_manager._paste_text` — was absent from
    dist entirely.  The build succeeded, the app started, and clipboard paste
    silently failed on every machine that did not also have the source tree.
    A missing module cannot be caught by "it builds", only by looking.
    """
    print("🔍 Verifying build contents...")
    app_dir, payload = _dist_root()

    exe_name = "DalalAI.exe" if sys.platform == "win32" else "DalalAI"
    exe_path = os.path.join(app_dir, exe_name)

    required_files = [
        exe_path,
        os.path.join(payload, "config.yaml"),
        os.path.join(payload, "dalal_ai", "ui", "app.py"),
        os.path.join(payload, "dalal_ai", "browser", "response_script.js"),
    ]
    required_dirs = [
        os.path.join(payload, "playwright", "driver"),
        os.path.join(payload, "streamlit", "static"),
    ]
    # Pure-Python packages live inside the PYZ archive embedded in the exe, so
    # they are invisible on disk.  The archive's table of contents stores module
    # names as plain text, so scanning the binary for them is a reliable check.
    required_modules = [
        "pyperclip",
        "pypdf",
        "dalal_ai.browser.browser_manager",
        "dalal_ai.core.document_extractor",
        "dalal_ai.core.swarm_orchestrator",
        "utils.paths",
        "streamlit.web.cli",
    ]

    problems = []
    for path in required_files:
        if not os.path.isfile(path):
            problems.append(f"missing file: {path}")
    for path in required_dirs:
        if not os.path.isdir(path):
            problems.append(f"missing directory: {path}")

    if os.path.isfile(exe_path):
        try:
            with open(exe_path, "rb") as fh:
                blob = fh.read()
            for module in required_modules:
                if module.encode("utf-8") not in blob:
                    problems.append(f"module not frozen into the exe: {module}")
        except OSError as exc:
            problems.append(f"could not read {exe_path}: {exc}")

    if problems:
        print("❌ Build verification FAILED:")
        for problem in problems:
            print(f"   • {problem}")
        print("\n   Check hiddenimports/datas in DalalAI.spec.")
        sys.exit(1)

    print("✅ Build verification passed.")


def prepare_release_files():
    print("📝 Preparing release artifacts...")
    # Write a simple README.txt and LICENSE for the release folder if they don't exist
    if not os.path.exists("README.txt"):
        with open("README.txt", "w") as f:
            f.write("Dalal AI\n========\n\nWindows: Run the Installer or extract the Zip to run.\nmacOS/Linux: Extract the archive and run the executable.\n")
    if not os.path.exists("LICENSE"):
        with open("LICENSE", "w") as f:
            f.write("MIT License (or equivalent). See source for details.\n")
    if not os.path.exists("CHANGELOG"):
        with open("CHANGELOG", "w") as f:
            f.write("Version 1.0.1\n- Added macOS and Linux build support.\n- Backward compatibility fixes for Python 3.8.\n\nVersion 1.0.0\n- Initial professional release\n")
            
    shutil.copy2("README.txt", "release/")
    shutil.copy2("LICENSE", "release/")
    shutil.copy2("CHANGELOG", "release/")

def build_installer():
    if sys.platform == "win32":
        print("💿 Building Inno Setup Installer...")
        # Inno Setup standard installation path
        iscc_path = r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        
        if not os.path.exists(iscc_path):
            print(f"⚠️ Warning: ISCC.exe not found at {iscc_path}.")
            print("Please install Inno Setup 6 to generate the installer, or update the path in build.py.")
            print("You can still find the standalone executable in the dist/DalalAI directory.")
            print("📦 Creating Zip archive fallback...")
            shutil.make_archive("release/DalalAI-Windows", "zip", "dist/DalalAI")
            return

        try:
            subprocess.run([iscc_path, r"installer\setup.iss"], check=True)
            print("✅ Installer generated successfully in release/")
        except subprocess.CalledProcessError as e:
            print(f"❌ Inno Setup failed: {e}")
            print("📦 Creating Zip archive fallback...")
            shutil.make_archive("release/DalalAI-Windows", "zip", "dist/DalalAI")
    elif sys.platform == "darwin":
        print("📦 Creating macOS archive...")
        shutil.make_archive("release/DalalAI-macOS", "zip", "dist/DalalAI")
        print("✅ macOS archive generated successfully in release/")
    elif sys.platform.startswith("linux"):
        print("📦 Creating Linux archive...")
        shutil.make_archive("release/DalalAI-Linux", "gztar", "dist/DalalAI")
        print("✅ Linux archive generated successfully in release/")
    else:
        print("📦 Creating generic archive...")
        shutil.make_archive(f"release/DalalAI-{sys.platform}", "zip", "dist/DalalAI")
        print("✅ Archive generated successfully in release/")

def main():
    print("🚀 Starting Dalal AI Build Process\n" + "="*40)
    clean()
    check_dependencies()
    build_exe()
    verify_build()
    prepare_release_files()
    build_installer()
    print("\n🎉 Build complete! Check the 'release' directory.")

if __name__ == "__main__":
    main()
