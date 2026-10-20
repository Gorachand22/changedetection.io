# CloakBrowser Stealth Fetcher Integration Manual for changedetection.io
========================================================================

> **Version:** 1.0 (Compatible with changedetection.io v0.60.8+)  
> **Platform:** Windows AMD64 / Python 3.14  
> **Environment:** Isolated `.venv` in repository root  
> **Backup Location:** `D:\changedetection_cloakbrowser_backup\`  

---

## 1. Executive Summary & Why This Works

### The Core Anti-Bot Problem
Standard fetchers (`requests`, raw `Playwright`, `Selenium`) fail against Cloudflare Turnstile, DataDome, and Akamai because of two distinct signals:
1. **Network / IP Signal:** Datacenter / Commercial ASNs (Oracle Cloud, AWS, DigitalOcean, Hetzner) are flagged globally by Cloudflare's IP reputation databases. Even the most stealthy browser will receive interactive Captchas purely based on Datacenter IP.
2. **Browser Fingerprint Signal:** Automated Chromium engines leak automation flags (`navigator.webdriver == true`, headless canvas/WebGL artifacts, lack of human mouse trajectories, default viewport flags).

### The Solution: Residential Windows + CloakBrowser
- **Running Locally on Windows:** Your home broadband (Airtel, Jio, ACT, etc.) provides a genuine **Residential Consumer ISP ASN**.
- **CloakBrowser Engine:** Wraps a custom C++ patched Chromium binary that spoofs canvas, WebGL, AudioContext, client hints, and emulates realistic human mouse Bezier trajectories (`humanize=True`).
- **Result:** Cloudflare Turnstile and DataDome treat the requests as a genuine human browsing from a home computer. Tested live on `https://nowsecure.nl` with **100% Turnstile bypass (HTTP 200)**.

---

## 2. Environment & Dependency Setup (`.venv`)

All dependencies are strictly isolated inside `d:\changedetection.io\.venv`, keeping the global Windows Python environment clean.

### Required Packages
```bash
# Inside d:\changedetection.io
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install "cloakbrowser[geoip]" playwright geoip2 maxminddb
```

### Stealth Chromium Binary
CloakBrowser manages its own custom C++ patched Chromium engine cached at:
`C:\Users\babul\.cloakbrowser\chromium-146.0.7680.177.5\chrome.exe`

---

## 3. Files Created (New Additions)

### File 1: `changedetectionio/content_fetchers/cloakbrowser.py`
This is the core content fetcher backend implementing changedetection's `Fetcher` abstract class and Pluggy hook.

#### Key Features & Architecture:
- **Capabilities Enabled:**
  ```python
  supports_browser_steps = True
  supports_screenshots = True
  supports_xpath_element_data = True
  ```
- **Stealth Launch Configuration:**
  ```python
  launch_args = [
      "--fingerprint-screen-width=1920",
      "--fingerprint-screen-height=1080",
      "--disable-dev-shm-usage",
      "--no-sandbox",
      "--disable-setuid-sandbox",
  ]
  browser = await cloakbrowser.launch_async(
      headless=self.headless,
      proxy=self.proxy,
      geoip=True,
      humanize=self.humanize,
      human_preset='default',
      stealth_args=True,
      args=launch_args,
  )
  ```
- **Visual Selector Element Extraction:**
  Injects `XPATH_ELEMENT_JS` to compute exact bounding boxes and XPaths of all text elements, storing them in `self.xpath_data` for changedetection's interactive Visual Selector overlay.
- **Full-Page Screenshot Capture:**
  Uses `capture_full_page_async()` to capture full viewport images and stores them in `self.screenshot`.
- **Cookie Injection & Persistent Profiles:**
  Supports cookie headers from watch settings and optional persistent browser sessions via `CLOAKBROWSER_PROFILE_DIR`.
- **Critical Architectural Fix (Do Not Delete!):**
  In `changedetection.io`, `processors/base.py` calls `await self.fetcher.quit()` *before* diffing and history saving. Therefore, `quit()` **must not** call `clear_content()`, preserving `self.content`, `self.screenshot`, and `self.xpath_data` for downstream processing.
- **Pluggy Registration:**
  ```python
  @hookimpl
  def get_fetcher_options():
      return [('html_cloakbrowser', 'CloakBrowser (Stealth Anti-Bot Chromium)')]
  ```

### File 2: `changedetectionio/static/images/cloakbrowser-icon.svg`
Custom purple stealth shield icon displayed next to watches using CloakBrowser in the dashboard table.

---

## 4. Files Modified (Line-by-Line Changes)

### File 3: `changedetectionio/content_fetchers/__init__.py`

#### Location: Bottom of the file (Lines 192–199)
> **IMPORTANT:** Do NOT place this import at the top of the file! Importing `cloakbrowser.py` at the top causes a circular import because `cloakbrowser.py` imports constants (`SCREENSHOT_MAX_HEIGHT_DEFAULT`, `XPATH_ELEMENT_JS`, etc.) from `changedetectionio.content_fetchers`.

```diff
--- a/changedetectionio/content_fetchers/__init__.py
+++ b/changedetectionio/content_fetchers/__init__.py
@@ -191,6 +192,11 @@ else:
     logger.debug("Falling back to selenium as fetcher")
     from .webdriver_selenium import fetcher as html_webdriver
 
+try:
+    from .cloakbrowser import fetcher as html_cloakbrowser
+except Exception as e:
+    logger.warning(f"CloakBrowser fetcher not available: {e}")
+
 
 # Register built-in fetchers as plugins after all imports are complete
 from changedetectionio.pluggy_interface import register_builtin_fetchers
```

---

### File 4: `changedetectionio/pluggy_interface.py`

#### Location: Inside `register_builtin_fetchers()` (Around line 315)
Registers CloakBrowser as a built-in Pluggy plugin so it appears in the dropdowns for Fetch Backend across the UI and API.

```diff
--- a/changedetectionio/pluggy_interface.py
+++ b/changedetectionio/pluggy_interface.py
@@ -314,6 +314,13 @@ def register_builtin_fetchers():
     if hasattr(webdriver_selenium, 'webdriver_selenium_plugin'):
         plugin_manager.register(webdriver_selenium.webdriver_selenium_plugin, 'builtin_webdriver_selenium')
 
+    try:
+        from changedetectionio.content_fetchers import cloakbrowser
+        if hasattr(cloakbrowser, 'cloakbrowser_plugin'):
+            plugin_manager.register(cloakbrowser.cloakbrowser_plugin, 'builtin_cloakbrowser')
+    except (ImportError, Exception):
+        pass
+
 
 def register_builtin_restock_plugins():
```

---

### File 5: `changedetectionio/flask_app.py`

#### Location: Inside `def static_content(group, filename):` (Lines 1172–1187 and 1230–1235)
> **Windows Path Bug Fix:** On Windows, when `changedetection.py` is started with `-d ./datastore`, relative paths passed to Flask/Werkzeug `send_from_directory()` can fail with 404. Wrapping directory paths in `os.path.abspath()` guarantees that screenshots and `elements.deflate` (Visual Selector data) load reliably.

```diff
--- a/changedetectionio/flask_app.py
+++ b/changedetectionio/flask_app.py
@@ -1168,9 +1168,10 @@ def changedetection_app(config=None, datastore_o=None):
             # These files should be in our subdirectory
             try:
                 # set nocache, set content-type
+                target_dir = os.path.abspath(os.path.join(datastore_o.datastore_path, filename))
                 response = make_response(
                     send_from_directory(
-                        os.path.join(datastore_o.datastore_path, filename), screenshot_filename
+                        target_dir, screenshot_filename
                     )
                 )
                 response.headers['Content-type'] = 'image/png'
@@ -1179,7 +1180,11 @@ def changedetection_app(config=None, datastore_o=None):
                 response.headers['Expires'] = 0
                 return response
 
-            except FileNotFoundError:
+            except FileNotFoundError as fnf:
+                logger.warning(f"Screenshot file not found for {filename}: {fnf}")
+                abort(404)
+            except Exception as e:
+                logger.warning(f"Error serving screenshot for {filename}: {e}")
                 abort(404)
 
@@ -1225,7 +1230,7 @@ def changedetection_app(config=None, datastore_o=None):
             try:
                 # set nocache, set content-type,
                 # `filename` is actually directory UUID of the watch
-                watch_directory = str(os.path.join(datastore_o.datastore_path, filename))
+                watch_directory = os.path.abspath(os.path.join(datastore_o.datastore_path, filename))
                 response = None
                 if os.path.isfile(os.path.join(watch_directory, "elements.deflate")):
                     response = make_response(
```

---

## 5. Future-Proofing: How to Adopt to New Upstream Versions

When `dgtlmoon/changedetection.io` releases a new version, choose any of the 3 automated methods below:

### Method A: One-Click Python Auto-Patch (Easiest & AI-Friendly)
We created a standalone auto-patcher script located at:
`D:\changedetection_cloakbrowser_backup\auto_patch.py` (and in repository root `auto_patch.py`).

After pulling the new version or cloning to a new folder, simply run:
```powershell
python D:\changedetection_cloakbrowser_backup\auto_patch.py D:\changedetection.io
```
**What it does automatically:**
1. Copies `cloakbrowser.py` and `cloakbrowser-icon.svg` into place.
2. Checks and injects the `html_cloakbrowser` import into `content_fetchers/__init__.py`.
3. Checks and injects `builtin_cloakbrowser` into `pluggy_interface.py`.
4. Checks and applies the `os.path.abspath` Windows fix into `flask_app.py`.

---

### Method B: Git Patch
The complete diff is saved as a universal Git patch:
`D:\changedetection_cloakbrowser_backup\cloakbrowser_integration.patch`

To apply it to any branch or fresh clone:
```powershell
cd D:\changedetection.io
git apply D:\changedetection_cloakbrowser_backup\cloakbrowser_integration.patch
```

---

### Method C: Git Branching & Rebase Workflow
Keep your changes on a dedicated branch so upstream updates merge automatically:

1. **Create and stay on your feature branch:**
   ```powershell
   git checkout -b feature/cloakbrowser-stealth
   git add changedetectionio/
   git commit -m "feat: integrate CloakBrowser stealth anti-bot fetcher"
   ```
2. **When an upstream version arrives:**
   ```powershell
   git checkout master
   git pull https://github.com/dgtlmoon/changedetection.io.git master
   git checkout feature/cloakbrowser-stealth
   git rebase master
   ```
   Git will automatically replay the CloakBrowser integration commits directly on top of the newest upstream release!

---

## 6. How to Run changedetection.io with CloakBrowser

```powershell
cd d:\changedetection.io
.\.venv\Scripts\python.exe changedetection.py -d ./datastore -p 5000 -h 127.0.0.1
```
- Open `http://127.0.0.1:5000`
- To monitor any Cloudflare or bot-protected target, set **Fetch Method** in watch edit settings to:
  `CloakBrowser (Stealth Anti-Bot Chromium)`
