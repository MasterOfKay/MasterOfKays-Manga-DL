"""
Updates of the app itself, from the GitHub releases of the project.

Pre-releases (GitHub's "pre-release" flag) are only listed and offered when
the user turns on beta updates.
"""

import io
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

import requests

from .. import __version__
from .events import EventBus

REPO = 'MasterOfKay/MasterOfKays-Manga-DL'
RELEASES_API = f'https://api.github.com/repos/{REPO}/releases?per_page=50'
RELEASES_PAGE = f'https://github.com/{REPO}/releases'
INTERVALS = {'hourly': 3600, 'daily': 86400, 'weekly': 7 * 86400, 'never': 0}

Version = Tuple[int, int, int, int, int]   # major, minor, patch, stage (0 alpha .. 3 final), stage number

_VERSION = re.compile(r'(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-_. ]?(alpha|beta|preview|pre|rc|a|b)\.?(\d*))?', re.I)
_STAGES = {'alpha': 0, 'a': 0, 'beta': 1, 'b': 1, 'pre': 1, 'preview': 1, 'rc': 2}


def parse_version(text: str, prerelease: bool = False) -> Optional[Version]:
    """'V1.3.1' -> (1, 3, 1, 3, 0), '3.1.0-beta.2' -> (3, 1, 0, 1, 2)."""
    match = _VERSION.search(text or '')
    if not match:
        return None
    major, minor, patch = (int(g or 0) for g in match.groups()[:3])
    stage = _STAGES.get((match.group(4) or '').lower(), 3)
    if prerelease and stage == 3:
        stage = 2           # marked pre-release on GitHub without a suffix: still older than the final
    return (major, minor, patch, stage, int(match.group(5) or 0))


def format_version(version: Version) -> str:
    major, minor, patch, stage, number = version
    text = f'{major}.{minor}' + (f'.{patch}' if patch else '')
    if stage < 3:
        text += '-' + ('alpha', 'beta', 'rc')[stage] + (f'.{number}' if number else '')
    return text


CURRENT: Version = parse_version(__version__) or (0, 0, 0, 3, 0)


@dataclass
class Release:
    tag: str
    name: str
    version: Version
    prerelease: bool
    published: Optional[datetime]
    notes: str
    page_url: str
    zip_url: str
    assets: List[dict] = field(default_factory=list)   # {'name', 'url', 'size'}

    @property
    def label(self) -> str:
        return format_version(self.version)

    @property
    def is_newer(self) -> bool:
        return self.version > CURRENT

    @property
    def is_current(self) -> bool:
        return self.version == CURRENT


def install_kind() -> str:
    if getattr(sys, 'frozen', False):
        return 'exe'
    if os.path.exists(os.path.join(app_root(), '.git')):
        return 'git'
    return 'source'


def app_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AppUpdater:
    def __init__(self, settings, bus: EventBus):
        self.settings = settings
        self.bus = bus
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._timer = threading.Thread(target=self._timer_loop, name="app-update-timer", daemon=True)
        self.releases: List[Release] = []        # every published release, newest first
        self.checking = False
        self.installing = False
        self.error = ''
        self.install_error = ''
        self.restart_command: Optional[List[str]] = None   # set once an update is in place
        self._cleanup_old_exe()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not self._timer.is_alive():
            self._timer.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ API
    @property
    def beta(self) -> bool:
        return bool(self.settings.get('app_updates.beta'))

    def visible_releases(self) -> List[Release]:
        """Releases to list: pre-releases only with beta updates turned on."""
        return [r for r in self.releases if self.beta or not r.prerelease]

    def available(self) -> Optional[Release]:
        """Newest release that may be installed (newer than this version)."""
        return next((r for r in self.visible_releases() if r.is_newer), None)

    def can_install(self, release: Release) -> bool:
        return release.is_newer and (self.beta or not release.prerelease)

    def last_check(self) -> Optional[datetime]:
        try:
            value = self.settings.get('app_updates.last_check', '')
            return datetime.fromisoformat(value) if value else None
        except ValueError:
            return None

    def check(self, manual: bool = True) -> bool:
        with self._lock:
            if self.checking:
                return False
            self.checking = True
        self.bus.emit('app_update_changed')
        threading.Thread(target=self._check, args=(manual,), name="app-update-check", daemon=True).start()
        return True

    def install(self, release: Release) -> bool:
        if not self.can_install(release) or install_kind() == 'git':
            return False
        with self._lock:
            if self.installing:
                return False
            self.installing = True
            self.install_error = ''
        self.bus.emit('app_update_changed')
        threading.Thread(target=self._install, args=(release,), name="app-update-install", daemon=True).start()
        return True

    # -------------------------------------------------------------- workers
    def _timer_loop(self) -> None:
        if self._stop.wait(15):            # let the app start first
            return
        while True:
            interval = INTERVALS.get(self.settings.get('app_updates.interval', 'daily'), 86400)
            last = self.last_check()
            if interval and (last is None or (datetime.now() - last).total_seconds() >= interval):
                self.check(manual=False)
            if self._stop.wait(60):
                return

    def _check(self, manual: bool) -> None:
        try:
            response = requests.get(RELEASES_API, timeout=20, headers={
                'Accept': 'application/vnd.github+json', 'User-Agent': 'MangaDL-updater'})
            if response.status_code == 403 and response.headers.get('X-RateLimit-Remaining') == '0':
                raise RuntimeError('GitHub rate limit reached - try again in an hour')
            response.raise_for_status()
            releases = [r for r in (self._parse(item) for item in response.json()) if r]
            releases.sort(key=lambda r: r.version, reverse=True)
            self.releases = releases
            self.error = ''
            self.settings.set('app_updates.last_check', datetime.now().isoformat(timespec='seconds'))
        except Exception as e:
            self.error = str(e) if isinstance(e, RuntimeError) else f"Couldn't reach GitHub ({type(e).__name__})"
            logging.warning(f"App update check failed: {e}")
        finally:
            self.checking = False
        self.bus.emit('app_update_changed')

        update = self.available()
        if self.error and manual:
            self.bus.emit('notify', 'manual', "Couldn't check for updates", self.error, 'error')
        elif update and (manual or self.settings.get('app_updates.notified') != update.tag):
            self.settings.set('app_updates.notified', update.tag)
            self.bus.emit('notify', 'manual' if manual else 'app_update', f"Manga DL {update.label} is available",
                          'Open the Updates page to see what changed and install it.', 'accent')
        elif manual and not self.error:
            self.bus.emit('notify', 'manual', "You're up to date", f"Version {format_version(CURRENT)} is the newest.",
                          'success')

    @staticmethod
    def _parse(item: dict) -> Optional[Release]:
        if item.get('draft'):
            return None
        prerelease = bool(item.get('prerelease'))
        version = parse_version(item.get('tag_name', ''), prerelease) or parse_version(item.get('name', ''), prerelease)
        if version is None:
            return None
        try:
            published = datetime.fromisoformat((item.get('published_at') or '').replace('Z', '+00:00'))
        except ValueError:
            published = None
        return Release(
            tag=item.get('tag_name', ''), name=(item.get('name') or item.get('tag_name') or '').strip(),
            version=version, prerelease=prerelease, published=published,
            notes=(item.get('body') or '').replace('\r\n', '\n').strip(),
            page_url=item.get('html_url') or RELEASES_PAGE, zip_url=item.get('zipball_url') or '',
            assets=[{'name': a.get('name', ''), 'url': a.get('browser_download_url', ''), 'size': a.get('size', 0)}
                    for a in item.get('assets', [])])

    def _install(self, release: Release) -> None:
        try:
            if install_kind() == 'exe':
                self.restart_command = self._install_exe(release)
            else:
                self.restart_command = self._install_source(release)
            logging.info(f"Installed update {release.tag}")
            self.bus.emit('notify', 'manual', f"Manga DL {release.label} is installed",
                          'Restart the app to use the new version.', 'success')
        except Exception as e:
            logging.exception("Installing the update failed")
            self.install_error = str(e)
            self.bus.emit('notify', 'manual', "The update couldn't be installed", str(e), 'error')
        finally:
            self.installing = False
            self.bus.emit('app_update_changed')

    def _download(self, url: str) -> bytes:
        with requests.get(url, stream=True, timeout=60, headers={'User-Agent': 'MangaDL-updater'}) as response:
            response.raise_for_status()
            total = int(response.headers.get('Content-Length') or 0)
            buffer = io.BytesIO()
            for chunk in response.iter_content(256 * 1024):
                buffer.write(chunk)
                self.bus.emit('app_update_progress', buffer.tell(), total)
        return buffer.getvalue()

    def _install_exe(self, release: Release) -> List[str]:
        asset = pick_asset(release.assets)
        if not asset:
            raise RuntimeError(f"Release {release.tag} has no download for this system")
        exe = sys.executable
        data = self._download(asset['url'])
        new, old = exe + '.new', exe + '.old'
        with open(new, 'wb') as f:
            f.write(data)
        if os.path.exists(old):
            os.remove(old)
        os.replace(exe, old)                 # a running exe can be renamed, not overwritten
        try:
            os.replace(new, exe)
        except OSError:
            os.replace(old, exe)             # put the working version back
            raise
        if sys.platform != 'win32':
            os.chmod(exe, 0o755)
        return [exe] + sys.argv[1:]

    def _install_source(self, release: Release) -> List[str]:
        if not release.zip_url:
            raise RuntimeError(f"Release {release.tag} has no source download")
        data = self._download(release.zip_url)
        root = app_root()
        with zipfile.ZipFile(io.BytesIO(data)) as archive, tempfile.TemporaryDirectory() as tmp:
            for member in archive.infolist():
                # GitHub zips have one top folder: "<owner>-<repo>-<sha>/..."
                parts = member.filename.split('/', 1)
                if len(parts) < 2 or not parts[1] or member.is_dir():
                    continue
                target = os.path.normpath(os.path.join(tmp, parts[1]))
                if not target.startswith(os.path.abspath(tmp) + os.sep):
                    continue                 # never write outside the folder
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(member) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            if not os.path.exists(os.path.join(tmp, 'main.py')):
                raise RuntimeError("The downloaded release doesn't look like Manga DL")
            shutil.copytree(tmp, root, dirs_exist_ok=True)
        return [sys.executable, os.path.join(root, 'main.py')]

    @staticmethod
    def _cleanup_old_exe() -> None:
        if getattr(sys, 'frozen', False):
            try:
                os.remove(sys.executable + '.old')
            except OSError:
                pass


def pick_asset(assets: List[dict]) -> Optional[dict]:
    """The release file for this operating system."""
    def has(asset, *words):
        name = asset['name'].lower()
        return any(w in name for w in words)

    if sys.platform == 'win32':
        candidates = [a for a in assets if a['name'].lower().endswith('.exe')]
        preferred = [a for a in candidates if has(a, 'win')]
    elif sys.platform == 'darwin':
        return None                      # an .app bundle can't be swapped like a single file
    else:
        candidates = [a for a in assets if has(a, 'linux', '.appimage')]
        preferred = []
    return (preferred or candidates or [None])[0]
