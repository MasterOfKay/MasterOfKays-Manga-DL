"""
UI-independent application core.
"""

from dataclasses import dataclass

from .app_updates import AppUpdater
from .browse import BrowseService
from .downloads import DownloadManager
from .events import EventBus
from .library import Library
from .updates import UpdateChecker


@dataclass
class AppCore:
    settings: object
    bus: EventBus
    library: Library
    downloads: DownloadManager
    updates: UpdateChecker
    browse: BrowseService
    app_updates: AppUpdater

    def start(self) -> None:
        self.downloads.start()
        self.updates.start()
        self.app_updates.start()

    def shutdown(self) -> None:
        self.updates.stop()
        self.app_updates.stop()
        self.downloads.shutdown()


def create_core() -> AppCore:
    from ..managers.database_manager import DatabaseManager
    from ..managers.settings_manager import SettingsManager

    settings = SettingsManager()
    bus = EventBus()
    library = Library(DatabaseManager(), settings, bus)
    downloads = DownloadManager(library, settings, bus)
    updates = UpdateChecker(library, downloads, settings, bus)
    return AppCore(settings, bus, library, downloads, updates, BrowseService(library, settings),
                   AppUpdater(settings, bus))
