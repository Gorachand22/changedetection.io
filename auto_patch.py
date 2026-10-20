#!/usr/bin/env python3
"""
Automated CloakBrowser Integration & Auto-Patch Script for changedetection.io
=============================================================================
This script automatically adopts and applies CloakBrowser integration
to ANY fresh clone or updated pull of changedetection.io.

Usage:
    python auto_patch.py [path_to_changedetection_repo]
Example:
    python auto_patch.py D:\changedetection.io
"""

import sys
import os
import shutil
import re

def patch_changedetection(repo_dir):
    repo_dir = os.path.abspath(repo_dir)
    print(f"[*] Applying CloakBrowser integration to: {repo_dir}")
    
    if not os.path.isdir(os.path.join(repo_dir, "changedetectionio")):
        print(f"[!] ERROR: {repo_dir} does not appear to be a valid changedetection.io repository!")
        sys.exit(1)

    backup_files_dir = os.path.join(r"D:\changedetection_cloakbrowser_backup", "files")
    if not os.path.isdir(backup_files_dir):
        backup_files_dir = os.path.join(repo_dir, "cloakbrowser_backup_files")

    # 1. Copy standalone files
    standalone_files = [
        os.path.join("changedetectionio", "content_fetchers", "cloakbrowser.py"),
        os.path.join("changedetectionio", "static", "images", "cloakbrowser-icon.svg"),
    ]

    for rel_path in standalone_files:
        src = os.path.join(backup_files_dir, rel_path)
        dst = os.path.join(repo_dir, rel_path)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  [+] Copied standalone file: {rel_path}")

    # 2. Patch changedetectionio/content_fetchers/__init__.py
    fetchers_init_path = os.path.join(repo_dir, "changedetectionio", "content_fetchers", "__init__.py")
    if os.path.isfile(fetchers_init_path):
        with open(fetchers_init_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if "html_cloakbrowser" not in content:
            injection = (
                "\n"
                "try:\n"
                "    from .cloakbrowser import fetcher as html_cloakbrowser\n"
                "except Exception as e:\n"
                "    logger.warning(f\"CloakBrowser fetcher not available: {e}\")\n\n"
            )
            marker = "# Register built-in fetchers as plugins after all imports are complete"
            if marker in content:
                content = content.replace(marker, injection + marker)
            else:
                content += injection
            
            with open(fetchers_init_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [+] Injected html_cloakbrowser into content_fetchers/__init__.py")
        else:
            print(f"  [=] content_fetchers/__init__.py already contains html_cloakbrowser")

    # 3. Patch changedetectionio/pluggy_interface.py
    pluggy_path = os.path.join(repo_dir, "changedetectionio", "pluggy_interface.py")
    if os.path.isfile(pluggy_path):
        with open(pluggy_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "builtin_cloakbrowser" not in content:
            pluggy_injection = (
                "    try:\n"
                "        from changedetectionio.content_fetchers import cloakbrowser\n"
                "        if hasattr(cloakbrowser, 'cloakbrowser_plugin'):\n"
                "            plugin_manager.register(cloakbrowser.cloakbrowser_plugin, 'builtin_cloakbrowser')\n"
                "    except (ImportError, Exception):\n"
                "        pass\n"
            )
            target = "def register_builtin_fetchers():"
            if target in content:
                marker = "def register_builtin_restock_plugins():"
                if marker in content:
                    idx = content.find(marker)
                    content = content[:idx] + pluggy_injection + "\n\n" + content[idx:]
                else:
                    content += "\n" + pluggy_injection
                
                with open(pluggy_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"  [+] Injected builtin_cloakbrowser registration into pluggy_interface.py")
        else:
            print(f"  [=] pluggy_interface.py already contains builtin_cloakbrowser")

    # 4. Patch changedetectionio/flask_app.py (Windows abspath for send_from_directory)
    flask_app_path = os.path.join(repo_dir, "changedetectionio", "flask_app.py")
    if os.path.isfile(flask_app_path):
        with open(flask_app_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Fix 1: screenshot send_from_directory
        old_screenshot_call = "send_from_directory(\n                        os.path.join(datastore_o.datastore_path, filename), screenshot_filename\n                    )"
        new_screenshot_call = "send_from_directory(\n                        os.path.abspath(os.path.join(datastore_o.datastore_path, filename)), screenshot_filename\n                    )"
        if old_screenshot_call in content:
            content = content.replace(old_screenshot_call, new_screenshot_call)
            print("  [+] Fixed screenshot send_from_directory path in flask_app.py")

        # Fix 2: visual_selector_data watch_directory
        old_watch_dir = "watch_directory = str(os.path.join(datastore_o.datastore_path, filename))"
        new_watch_dir = "watch_directory = os.path.abspath(os.path.join(datastore_o.datastore_path, filename))"
        if old_watch_dir in content:
            content = content.replace(old_watch_dir, new_watch_dir)
            print("  [+] Fixed visual_selector_data watch_directory path in flask_app.py")

        with open(flask_app_path, "w", encoding="utf-8") as f:
            f.write(content)

    print("\n[✓] CloakBrowser integration successfully applied to changedetection.io!")
    print("[*] To launch changedetection with CloakBrowser:")
    print(f"    cd {repo_dir}")
    print(f"    .\\.venv\\Scripts\\python.exe changedetection.py -d ./datastore -p 5000 -h 127.0.0.1")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else r"D:\changedetection.io"
    patch_changedetection(target)
