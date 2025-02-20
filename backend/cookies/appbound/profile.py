import os
from pathlib import Path
import typing

ChromiumBrowsers = typing.Literal['chrome', 'brave', 'edge', 'chromium']


def get_browser_executable(browser: ChromiumBrowsers) -> str | None:
    browser_path = {
        "chrome": r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        "brave": r'C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe',
        "edge": r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        "chromium": r'C:\Program Files\Chromium\Application\chrome.exe',
    }[browser]
    if not os.path.exists(browser_path):
        return None
    return browser_path


def get_browser_profile(browser: ChromiumBrowsers) -> str | None:
    """
    Determine browser profile path based on file existence.

    Args:
        browser: Browser name

    Returns:
        str: Path to user profile if found, None otherwise
    """

    basedirs = [os.getenv(key) for key in ['LOCALAPPDATA', 'APPDATA'] if os.getenv(key)]

    browser_paths = {
        "chrome": {
            "base_paths": [
                "{basedir}/Google/Chrome{channel}/User Data/Default/Cookies",
                "{basedir}/Google/Chrome{channel}/User Data/Default/Network/Cookies",
            ],
            "channels": ["", "-beta", "-dev", "-nightly"],
        },
        "brave": {
            "base_paths": [
                "{basedir}/BraveSoftware/Brave-Browser{channel}/User Data/Default/Cookies",
                "{basedir}/BraveSoftware/Brave-Browser{channel}/User Data/Default/Network/Cookies",
            ],
            "channels": ["", "-beta", "-dev", "-nightly"],
        },
        "edge": {
            "base_paths": [
                "{basedir}/Microsoft/Edge{channel}/User Data/Default/Cookies",
                "{basedir}/Microsoft/Edge{channel}/User Data/Default/Network/Cookies",
            ],
            "channels": ["", "-beta", "-dev", "-nightly"],
        },
        "chromium": {
            "base_paths": [
                "{basedir}/Chromium{channel}/User Data/Default/Cookies",
                "{basedir}/Chromium{channel}/User Data/Default/Network/Cookies",
            ],
            "channels": [""],
        },
    }

    if browser not in browser_paths:
        return None

    browser_config = browser_paths[browser]

    # Check each possible path combination
    for basedir in basedirs:
        for base_path in browser_config["base_paths"]:
            for channel in browser_config["channels"]:
                # Format path with channel
                full_path = base_path.format(basedir=basedir, channel=channel)
                cookie_path = Path(full_path)

                if cookie_path.exists():
                    while not os.path.basename(cookie_path) == 'User Data':
                        cookie_path = cookie_path.parent
                    return str(cookie_path)
    return None
