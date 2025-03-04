#!/usr/bin/env python3
"""
Launcher that checks requirements and runs the appropriate interface
"""

import os
import sys
import subprocess
import platform

def check_dependencies():
    """Check which dependencies are installed"""
    try:
        import PyQt5
        has_pyqt = True
    except ImportError:
        has_pyqt = False
    
    try:
        import requests
        import bs4
        has_core_deps = True
    except ImportError:
        has_core_deps = False
    
    return has_core_deps, has_pyqt

def print_header():
    """Print program header"""
    print("=" * 60)
    print("MANGA DOWNLOADER".center(60))
    print("=" * 60)
    print()

def launch_gui_without_console():
    """Launch the GUI without showing a console window"""
    if platform.system() == 'Windows':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        
        pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(pythonw):
            pythonw = 'pythonw'
            
        subprocess.Popen([pythonw, "manga_downloader_gui.py"], 
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen([sys.executable, "manga_downloader_gui.py"],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

def main():
    """Run the appropriate interface based on available dependencies"""
    print_header()
    print("Checking dependencies...")
    
    core_deps, has_pyqt = check_dependencies()
    
    if not core_deps:
        print("\nRequired dependencies not found. Please install them with:")
        print("pip install -r requirements.txt")
        return
    
    if os.path.exists("manga_downloader_gui.py") and has_pyqt:
        print("Found PyQt5. Starting GUI version...")
        launch_gui_without_console()
        print("\nGUI started! You can close this window.")
    elif os.path.exists("enhanced_dl.py"):
        print("Starting enhanced CLI version...")
        os.system(f"{sys.executable} enhanced_dl.py")
    else:
        print("Starting basic CLI version...")
        os.system(f"{sys.executable} dl.py")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        input("Press Enter to exit...")
