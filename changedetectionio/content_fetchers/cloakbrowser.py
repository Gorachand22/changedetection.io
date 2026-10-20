import asyncio
import gc
import json
import os
import time
from urllib.parse import urlparse
from loguru import logger

from changedetectionio.content_fetchers import (
    SCREENSHOT_MAX_HEIGHT_DEFAULT,
    visualselector_xpath_selectors,
    SCREENSHOT_MAX_TOTAL_HEIGHT,
    XPATH_ELEMENT_JS,
    INSTOCK_DATA_JS,
    FAVICON_FETCHER_JS,
)
from changedetectionio.content_fetchers.base import (
    Fetcher,
    manage_user_agent,
)
from changedetectionio.content_fetchers.exceptions import (
    PageUnloadable,
    Non200ErrorCodeReceived,
    EmptyReply,
    ScreenshotUnavailable,
    BrowserStepsStepException,
)
from changedetectionio.content_fetchers.playwright import capture_full_page_async
from changedetectionio.strtobool import strtobool


class fetcher(Fetcher):
    """CloakBrowser Stealth Chromium Content Fetcher.
    
    Uses CloakBrowser's custom C++ patched Chromium binary to bypass anti-bot
    systems like Cloudflare Turnstile, Datadome, Akamai, and perimeter WAFs.
    Supports full Playwright async automation, Visual Selector XPath extraction,
    full-page screenshots, cookie injection, and persistent profiles.
    """

    fetcher_description = "CloakBrowser (Stealth Anti-Bot Chromium)"

    supports_browser_steps = True
    supports_screenshots = True
    supports_xpath_element_data = True

    proxy = None
    headless = True
    humanize = True
    persistent_context = False
    profile_dir = None

    @classmethod
    def get_status_icon_data(cls):
        """Return icon data for CloakBrowser stealth fetcher."""
        return {
            'filename': 'cloakbrowser-icon.svg',
            'alt': 'Using CloakBrowser Stealth Chromium',
            'title': 'Using CloakBrowser Stealth Chromium (Anti-Bot Bypass)',
        }

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)

        # Allow headless toggle via environment variable (default: True)
        self.headless = strtobool(os.getenv("CLOAKBROWSER_HEADLESS", "true"))

        # Enable human-like mouse/keyboard movement (default: True)
        self.humanize = strtobool(os.getenv("CLOAKBROWSER_HUMANIZE", "true"))

        # Support proxy configuration
        if proxy_override:
            self.proxy = proxy_override
        else:
            self.proxy = os.getenv("CLOAKBROWSER_PROXY", None)

        # Allow persistent profiles across checks for sessions/cookies
        self.profile_dir = os.getenv("CLOAKBROWSER_PROFILE_DIR", None)

    async def screenshot_step(self, step_n=''):
        super().screenshot_step(step_n=step_n)
        watch_uuid = getattr(self, 'watch_uuid', None)
        screenshot = await capture_full_page_async(
            page=self.page,
            screenshot_format=self.screenshot_format,
            watch_uuid=watch_uuid,
            lock_viewport_elements=self.lock_viewport_elements
        )

        try:
            await self.page.request_gc()
        except Exception:
            pass

        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, f'step_{step_n}.jpeg')
            logger.debug(f"Saving step screenshot to {destination}")
            with open(destination, 'wb') as f:
                f.write(screenshot)
            del screenshot
            gc.collect()

    async def save_step_html(self, step_n):
        super().save_step_html(step_n=step_n)
        content = await self.page.content()

        try:
            await self.page.request_gc()
        except Exception:
            pass

        destination = os.path.join(self.browser_steps_screenshot_path, f'step_{step_n}.html')
        logger.debug(f"Saving step HTML to {destination}")
        with open(destination, 'w', encoding='utf-8') as f:
            f.write(content)
        del content
        gc.collect()

    async def run(
        self,
        fetch_favicon=True,
        current_include_filters=None,
        empty_pages_are_a_change=False,
        ignore_status_codes=False,
        is_binary=False,
        request_body=None,
        request_headers=None,
        request_method=None,
        screenshot_format=None,
        timeout=None,
        url=None,
        watch_uuid=None,
    ):
        try:
            import cloakbrowser
        except ImportError:
            error_msg = (
                "CloakBrowser Python package is not installed! "
                "Install it using: pip install cloakbrowser"
            )
            logger.error(error_msg)
            self.error = error_msg
            raise PageUnloadable(url=url, status_code=None, message=error_msg)

        self.delete_browser_steps_screenshots()
        self.watch_uuid = watch_uuid
        self.screenshot_format = screenshot_format

        browser = None
        context = None
        self.page = None
        response = None

        timeout_ms = (timeout * 1000) if timeout else 60000

        try:
            # Determine if persistent profile should be used for this watch
            profile_path = None
            if self.profile_dir:
                profile_path = os.path.join(self.profile_dir, watch_uuid if watch_uuid else "default")
                os.makedirs(profile_path, exist_ok=True)

            logger.info(
                f"Launching CloakBrowser Stealth Chromium for {url} "
                f"(headless={self.headless}, humanize={self.humanize}, profile={profile_path is not None})"
            )

            launch_args = [
                "--fingerprint-screen-width=1920",
                "--fingerprint-screen-height=1080",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]

            # Launch either persistent context or clean browser instance
            if profile_path:
                context = await cloakbrowser.launch_persistent_context_async(
                    user_data_dir=profile_path,
                    headless=self.headless,
                    proxy=self.proxy,
                    geoip=True,
                    humanize=self.humanize,
                    human_preset='default',
                    stealth_args=True,
                    args=launch_args,
                    user_agent=manage_user_agent(headers=request_headers or {}),
                    extra_http_headers=request_headers or {},
                    ignore_https_errors=True,
                )
                self.page = context.pages[0] if context.pages else await context.new_page()
            else:
                browser = await cloakbrowser.launch_async(
                    headless=self.headless,
                    proxy=self.proxy,
                    geoip=True,
                    humanize=self.humanize,
                    human_preset='default',
                    stealth_args=True,
                    args=launch_args,
                )
                context = await browser.new_context(
                    accept_downloads=False,
                    extra_http_headers=request_headers or {},
                    ignore_https_errors=True,
                    user_agent=manage_user_agent(headers=request_headers or {}),
                )
                self.page = await context.new_page()

            # Set viewport to standard desktop resolution
            await self.page.set_viewport_size({"width": 1280, "height": 1024})

            # Check for cookie injection from request headers
            if request_headers and 'cookie' in {k.lower(): k for k in request_headers}:
                cookie_str = None
                for k, v in request_headers.items():
                    if k.lower() == 'cookie':
                        cookie_str = v
                        break
                if cookie_str:
                    parsed_domain = urlparse(url).netloc
                    cookies_to_add = []
                    for item in cookie_str.split(';'):
                        if '=' in item:
                            c_name, c_val = item.strip().split('=', 1)
                            cookies_to_add.append({
                                'name': c_name.strip(),
                                'value': c_val.strip(),
                                'domain': parsed_domain,
                                'path': '/'
                            })
                    if cookies_to_add:
                        try:
                            await context.add_cookies(cookies_to_add)
                            logger.debug(f"CloakBrowser: Injected {len(cookies_to_add)} custom cookies for {parsed_domain}")
                        except Exception as ce:
                            logger.warning(f"CloakBrowser: Failed to inject custom cookies: {ce}")

            # Navigation tracking
            from changedetectionio.browser_steps.browser_steps import (
                steppable_browser_interface,
                track_latest_navigation_response,
            )

            latest_nav = track_latest_navigation_response(self.page)
            if latest_nav is None:
                latest_nav = {}

            self.page.on(
                "console",
                lambda msg: logger.debug(f"CloakBrowser console: [{url}] {msg.type}: {msg.text}")
            )

            # Navigate using standard browsersteps interface
            browsersteps_interface = steppable_browser_interface(start_url=url)
            browsersteps_interface.page = self.page

            response = await browsersteps_interface.action_goto_url(value=url)

            if response is None:
                logger.debug("CloakBrowser > Response object was None")
                raise EmptyReply(url=url, status_code=None)

            # Extract response headers
            try:
                self.headers = await response.all_headers()
            except TypeError:
                self.headers = response.all_headers()

            # Custom JavaScript execution if requested
            if self.webdriver_js_execute_code and self.webdriver_js_execute_code.strip():
                try:
                    await browsersteps_interface.action_execute_js(
                        value=self.webdriver_js_execute_code, selector=None
                    )
                except Exception as e:
                    logger.warning(f"CloakBrowser > Custom JS execution warning: {e}")

            # Webdriver delay before extracting content
            extra_wait = int(os.getenv("WEBDRIVER_DELAY_BEFORE_CONTENT_READY", 5)) + self.render_extract_delay
            await self.page.wait_for_timeout(extra_wait * 1000)

            # Check if a client-side or meta-refresh navigation landed
            latest = latest_nav.get('response')
            if latest is not None and latest is not response:
                logger.debug(
                    f"CloakBrowser: Page navigated again to {latest.url} (status {latest.status})"
                )
                response = latest
                try:
                    self.headers = await response.all_headers()
                except Exception:
                    pass

            # Wait for DOM to settle
            try:
                await self.page.wait_for_load_state('load', timeout=extra_wait * 1000)
            except Exception:
                pass

            try:
                self.status_code = response.status
            except Exception as e:
                logger.critical(f"CloakBrowser: No status_code in response: {e}")
                raise PageUnloadable(url=url, status_code=None, message=str(e))

            # Favicon extraction
            if fetch_favicon:
                try:
                    self.favicon_blob = await self.page.evaluate(FAVICON_FETCHER_JS)
                    await self.page.request_gc()
                except Exception as e:
                    logger.debug(f"FavIcon extraction note: {e}")

            # Non-200 check
            if self.status_code != 200 and not ignore_status_codes:
                screenshot = await capture_full_page_async(
                    self.page,
                    screenshot_format=self.screenshot_format,
                    watch_uuid=watch_uuid,
                    lock_viewport_elements=self.lock_viewport_elements
                )
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

            # Check for empty reply
            content_text = (await self.page.content()).strip()
            if not empty_pages_are_a_change and len(content_text) == 0:
                raise EmptyReply(url=url, status_code=response.status)

            # Browser Steps iteration
            if self.browser_steps:
                try:
                    await self.iterate_browser_steps(start_url=url)
                except BrowserStepsStepException:
                    raise
                await self.page.wait_for_timeout(extra_wait * 1000)

            # Set include_filters variable in page
            if current_include_filters is not None:
                await self.page.evaluate(f"var include_filters={json.dumps(current_include_filters)}")
            else:
                await self.page.evaluate("var include_filters=''")

            # Extract Visual Selector XPath Data
            max_height = int(os.getenv("SCREENSHOT_MAX_HEIGHT", SCREENSHOT_MAX_HEIGHT_DEFAULT))
            self.xpath_data = await self.page.evaluate(
                XPATH_ELEMENT_JS,
                {
                    "visualselector_xpath_selectors": visualselector_xpath_selectors,
                    "max_height": max_height,
                }
            )

            # Extract In-Stock data
            try:
                self.instock_data = await self.page.evaluate(INSTOCK_DATA_JS)
            except Exception as e:
                logger.debug(f"In-stock evaluation note: {e}")

            # Extract final DOM content
            self.content = await self.page.content()

            # Capture Full Page Screenshot
            self.screenshot = await capture_full_page_async(
                page=self.page,
                screenshot_format=self.screenshot_format,
                watch_uuid=watch_uuid,
                lock_viewport_elements=self.lock_viewport_elements
            )

            logger.info(f"CloakBrowser: Successfully fetched {url} (content: {len(self.content)} bytes)")

        except ScreenshotUnavailable:
            raise ScreenshotUnavailable(url=url, status_code=self.status_code)
        except (PageUnloadable, Non200ErrorCodeReceived, EmptyReply, BrowserStepsStepException):
            raise
        except Exception as e:
            logger.error(f"CloakBrowser fetching error for {url}: {e}")
            raise PageUnloadable(url=url, status_code=getattr(self, 'status_code', None), message=str(e))
        finally:
            # Clean up browser and memory aggressively to prevent leaks
            try:
                if self.page:
                    await asyncio.wait_for(self.page.close(), timeout=5.0)
            except Exception:
                pass
            finally:
                self.page = None

            try:
                if context:
                    await asyncio.wait_for(context.close(), timeout=5.0)
            except Exception:
                pass
            finally:
                context = None

            try:
                if browser:
                    await asyncio.wait_for(browser.close(), timeout=5.0)
            except Exception:
                pass
            finally:
                browser = None

            gc.collect()

    async def quit(self, watch=None):
        """Cleanup hook called after fetch operations."""
        # Do not clear content here as downstream processors (diff, AI, filters)
        # require self.content and self.screenshot in run_changedetection().
        gc.collect()


# Plugin registration class for pluggy integration
class CloakBrowserFetcherPlugin:
    """Plugin class registering the CloakBrowser content fetcher."""

    def register_content_fetcher(self):
        """Register the CloakBrowser stealth fetcher."""
        return ('html_cloakbrowser', fetcher)


# Module-level instance for pluggy
cloakbrowser_plugin = CloakBrowserFetcherPlugin()
