import os
import sys
import shutil
import subprocess

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

def prepare_release_files():
    print("📝 Preparing release artifacts...")
    # Write a simple README.txt and LICENSE for the release folder if they don't exist
    if not os.path.exists("README.txt"):
        with open("README.txt", "w") as f:
            f.write("Dalal AI\n========\n\nRun DalalAI_Setup.exe to install.\n")
    if not os.path.exists("LICENSE"):
        with open("LICENSE", "w") as f:
            f.write("MIT License (or equivalent). See source for details.\n")
    if not os.path.exists("CHANGELOG"):
        with open("CHANGELOG", "w") as f:
            f.write("Version 1.0.0\n- Initial professional release\n")
            
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
    prepare_release_files()
    build_installer()
    print("\n🎉 Build complete! Check the 'release' directory.")

if __name__ == "__main__":
    main()
