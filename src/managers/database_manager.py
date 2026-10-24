"""
Database manager for manga metadata and history using SQLite.
"""

import sqlite3
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class MangaMetadata:
    """Manga metadata structure."""
    title: str
    url: str
    site_type: str
    description: str = ""
    author: str = ""
    genres: Optional[List[str]] = None
    status: str = "unknown"  # ongoing, completed, cancelled
    release_date: str = ""
    alternative_names: Optional[List[str]] = None
    cover_image_url: str = ""
    language: str = "en"
    translation_type: str = "official"
    last_updated: str = ""
    first_download: str = ""
    
    def __post_init__(self):
        if self.genres is None:
            self.genres = []
        if self.alternative_names is None:
            self.alternative_names = []


@dataclass
class ChapterData:
    """Chapter data structure."""
    chapter_number: str
    chapter_name: str
    chapter_url: str
    language: str = "en"
    volume_number: str = ""
    is_downloaded: bool = False
    download_date: str = ""
    file_path: str = ""
    free_at: str = ""        # ISO time (UTC) an early-access chapter becomes free; '' = always free
    group_name: str = ""     # release group of the chosen upload
    group_locked: bool = False   # picked by the user for this chapter
    sources: str = ""        # JSON list of every group's upload when there are several


class DatabaseManager:
    """Manages SQLite database for manga metadata and history."""
    
    def __init__(self):
        self.db_dir = os.path.join(os.path.expanduser("~"), ".mangadownloader")
        self.db_path = os.path.join(self.db_dir, "manga_database.db")
        self.old_history_path = os.path.join(self.db_dir, "history.json")
        
        os.makedirs(self.db_dir, exist_ok=True)
        self._initialize_database()
        self._migrate_database_schema()
        self._migrate_from_json()
        
    def _connect(self) -> sqlite3.Connection:
        """Open a connection. Each call gets its own connection so it is safe
        to use from background threads; the timeout avoids 'database is locked'
        errors when the downloader and the update checker write at once."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_database(self):
        """Initialize the SQLite database with required tables."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS manga (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL,
                        site_type TEXT NOT NULL,
                        description TEXT DEFAULT '',
                        author TEXT DEFAULT '',
                        genres TEXT DEFAULT '',  -- JSON array of genres
                        status TEXT DEFAULT 'unknown',
                        release_date TEXT DEFAULT '',
                        alternative_names TEXT DEFAULT '',  -- JSON array of alternative names
                        cover_image_url TEXT DEFAULT '',
                        cover_image_path TEXT DEFAULT '',
                        language TEXT DEFAULT 'en',
                        translation_type TEXT DEFAULT 'official',
                        first_download TEXT NOT NULL,
                        last_updated TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(title, language)  -- Allow same manga in different languages
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chapters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        manga_id INTEGER NOT NULL,
                        chapter_number TEXT NOT NULL,
                        chapter_name TEXT NOT NULL,
                        chapter_url TEXT NOT NULL,
                        language TEXT DEFAULT 'en',
                        is_downloaded BOOLEAN DEFAULT FALSE,
                        download_date TEXT DEFAULT '',
                        file_path TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (manga_id) REFERENCES manga (id) ON DELETE CASCADE,
                        UNIQUE(manga_id, chapter_number, language)
                    )
                ''')
                
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_manga_title ON manga(title)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_manga_site ON manga(site_type)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_chapters_manga ON chapters(manga_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_chapters_downloaded ON chapters(is_downloaded)')
                
                conn.commit()
                logging.info("Database initialized successfully")
                
        except Exception as e:
            logging.error(f"Error initializing database: {e}")
            raise
    
    def _migrate_database_schema(self):
        """Migrate existing database schema to add new columns."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute("PRAGMA table_info(manga)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'language' not in columns:
                    logging.info("Adding language column to manga table")
                    cursor.execute("ALTER TABLE manga ADD COLUMN language TEXT DEFAULT 'en'")
                
                if 'last_page_scanned' not in columns:
                    logging.info("Adding chapter scanning tracking columns to manga table")
                    cursor.execute("ALTER TABLE manga ADD COLUMN last_page_scanned INTEGER DEFAULT 0")
                    cursor.execute("ALTER TABLE manga ADD COLUMN total_pages INTEGER DEFAULT 0")
                    cursor.execute("ALTER TABLE manga ADD COLUMN last_chapter_scan TEXT DEFAULT ''")
                    cursor.execute("ALTER TABLE manga ADD COLUMN chapters_cached INTEGER DEFAULT 0")
                
                if 'translation_type' not in columns:
                    logging.info("Adding translation_type column to manga table")
                    cursor.execute("ALTER TABLE manga ADD COLUMN translation_type TEXT DEFAULT 'official'")
                
                cursor.execute("PRAGMA table_info(chapters)")
                chapters_columns = [column[1] for column in cursor.fetchall()]
                
                if 'language' not in chapters_columns:
                    logging.info("Adding language column to chapters table")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN language TEXT DEFAULT 'en'")
                
                if 'volume_number' not in chapters_columns:
                    logging.info("Adding volume_number column to chapters table")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN volume_number TEXT DEFAULT ''")

                if 'is_new' not in chapters_columns:
                    logging.info("Adding is_new column to chapters table")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN is_new INTEGER DEFAULT 0")

                if 'last_checked' not in columns:
                    logging.info("Adding last_checked column to manga table")
                    cursor.execute("ALTER TABLE manga ADD COLUMN last_checked TEXT DEFAULT ''")

                # Older versions re-inserted manga rows (new id) on every metadata
                # refresh, leaving chapters pointing at ids that no longer exist.
                cursor.execute("DELETE FROM chapters WHERE manga_id NOT IN (SELECT id FROM manga)")
                if cursor.rowcount:
                    logging.info(f"Removed {cursor.rowcount} orphaned chapter rows")
                
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='chapters'")
                chapters_table_sql = cursor.fetchone()
                if chapters_table_sql and 'UNIQUE(manga_id, chapter_number, language)' not in chapters_table_sql[0]:
                    logging.info("Migrating chapters table UNIQUE constraint to include language")
                    try:
                        cursor.execute('''
                            CREATE TABLE IF NOT EXISTS chapters_new (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                manga_id INTEGER NOT NULL,
                                chapter_number TEXT NOT NULL,
                                chapter_name TEXT NOT NULL,
                                chapter_url TEXT NOT NULL,
                                language TEXT DEFAULT 'en',
                                is_downloaded BOOLEAN DEFAULT FALSE,
                                download_date TEXT DEFAULT '',
                                file_path TEXT DEFAULT '',
                                volume_number TEXT DEFAULT '',
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY (manga_id) REFERENCES manga (id) ON DELETE CASCADE,
                                UNIQUE(manga_id, chapter_number, language)
                            )
                        ''')
                        cursor.execute('''
                            INSERT OR IGNORE INTO chapters_new
                                (id, manga_id, chapter_number, chapter_name, chapter_url,
                                 language, is_downloaded, download_date, file_path, volume_number,
                                 created_at, updated_at)
                            SELECT id, manga_id, chapter_number, chapter_name, chapter_url,
                                   COALESCE(language, 'en'), is_downloaded,
                                   COALESCE(download_date, ''), COALESCE(file_path, ''),
                                   COALESCE(volume_number, ''), created_at, updated_at
                            FROM chapters
                        ''')
                        cursor.execute('DROP TABLE chapters')
                        cursor.execute('ALTER TABLE chapters_new RENAME TO chapters')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chapters_manga ON chapters(manga_id)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chapters_downloaded ON chapters(is_downloaded)')
                        logging.info("Chapters table migrated to include language in UNIQUE constraint")
                    except Exception as migrate_err:
                        logging.error(f"Error migrating chapters table: {migrate_err}")
                
                # After the rebuild above, which would drop it again.
                cursor.execute("PRAGMA table_info(chapters)")
                if 'free_at' not in [column[1] for column in cursor.fetchall()]:
                    logging.info("Adding free_at (early access) column to chapters table")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN free_at TEXT DEFAULT ''")
                cursor.execute("PRAGMA table_info(chapters)")
                chapters_columns = [column[1] for column in cursor.fetchall()]
                if 'group_name' not in chapters_columns:
                    logging.info("Adding release group columns to chapters table")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN group_name TEXT DEFAULT ''")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN group_locked INTEGER DEFAULT 0")
                    cursor.execute("ALTER TABLE chapters ADD COLUMN sources TEXT DEFAULT ''")
                if 'preferred_group' not in columns:
                    logging.info("Adding preferred_group column to manga table")
                    cursor.execute("ALTER TABLE manga ADD COLUMN preferred_group TEXT DEFAULT ''")

                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='manga'")
                table_sql = cursor.fetchone()
                if table_sql and 'UNIQUE(title, language)' not in table_sql[0]:
                    logging.info("Updating manga table unique constraint to include language")
                    logging.warning("Unique constraint update skipped - may cause duplicate entries")
                
                conn.commit()
                logging.info("Database schema migration completed successfully")
                
        except Exception as e:
            logging.error(f"Error migrating database schema: {e}")
            
    def _migrate_from_json(self):
        """Migrate data from old JSON history file to SQLite database."""
        json_file_to_migrate = None
        source_description = ""
        
        if os.path.exists(self.old_history_path):
            json_file_to_migrate = self.old_history_path
            source_description = "active history.json"
        else:
            backup_candidates = []
            
            backup_path = self.old_history_path + ".backup"
            if os.path.exists(backup_path):
                backup_candidates.append((backup_path, "history.json.backup"))
            
            import glob
            timestamped_backups = glob.glob(self.old_history_path + ".backup.*")
            for backup in timestamped_backups:
                backup_candidates.append((backup, os.path.basename(backup)))
            
            if backup_candidates:
                backup_candidates.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
                json_file_to_migrate, backup_name = backup_candidates[0]
                source_description = f"backup file ({backup_name})"
                logging.info(f"No active history.json found, but found {len(backup_candidates)} backup files")
                logging.info(f"Using most recent backup: {backup_name}")
        
        if not json_file_to_migrate:
            return
            
        try:
            with open(json_file_to_migrate, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
            
            logging.info(f"Migrating {len(old_data)} manga entries from {source_description} to SQLite database")
            
            for manga_name, manga_data in old_data.items():
                metadata = MangaMetadata(
                    title=manga_name,
                    url=manga_data.get('url', ''),
                    site_type=manga_data.get('site_type', 'unknown'),
                    first_download=manga_data.get('first_download', datetime.now().isoformat()),
                    last_updated=manga_data.get('last_updated', datetime.now().isoformat())
                )
                
                manga_id = self.add_or_update_manga(metadata)
                
                chapters = manga_data.get('chapters', {})
                for chapter_num, chapter_info in chapters.items():
                    chapter_data = ChapterData(
                        chapter_number=chapter_num,
                        chapter_name=f"Chapter {chapter_num}",
                        chapter_url=chapter_info.get('url', ''),
                        is_downloaded=True,
                        download_date=chapter_info.get('download_date', '')
                    )
                    self.add_or_update_chapter(manga_id, chapter_data)
            
            if json_file_to_migrate == self.old_history_path:
                backup_path = self.old_history_path + ".backup"
                if os.path.exists(backup_path):
                    import time
                    timestamp = int(time.time())
                    backup_path = f"{self.old_history_path}.backup.{timestamp}"
                
                os.rename(self.old_history_path, backup_path)
                logging.info(f"Migration from active file complete. Old file backed up to {backup_path}")
            else:
                logging.info(f"Migration from backup file complete. Backup file preserved at {json_file_to_migrate}")
                
                migration_flag = os.path.join(self.db_dir, ".migrated_from_backup")
                with open(migration_flag, 'w') as f:
                    f.write(f"Migrated from: {json_file_to_migrate}\n")
                    f.write(f"Migration date: {datetime.now().isoformat()}\n")
            
        except Exception as e:
            logging.error(f"Error migrating from JSON ({source_description}): {e}")
    
    def rename_manga_title(self, manga_id: int, new_title: str) -> bool:
        """Rename a manga title in-place (UPDATE only, preserves chapter links)."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE manga SET title = ? WHERE id = ?', (new_title, manga_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"Error renaming manga ID {manga_id}: {e}")
            return False

    def add_or_update_manga(self, metadata: MangaMetadata, cover_image_path: str = "") -> int:
        """Add or update manga metadata. Returns the manga ID.

        Existing rows are updated in place so the ID (and with it every chapter
        row pointing at it) stays stable. Empty incoming values never overwrite
        data we already have.
        """
        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                genres_json = json.dumps(metadata.genres) if metadata.genres else '[]'
                alt_names_json = json.dumps(metadata.alternative_names) if metadata.alternative_names else '[]'

                cursor.execute('SELECT id FROM manga WHERE title = ? AND language = ?',
                               (metadata.title, metadata.language))
                row = cursor.fetchone()
                if row is None:
                    cursor.execute('SELECT id FROM manga WHERE url = ?', (metadata.url,))
                    row = cursor.fetchone()

                if row:
                    manga_id = row[0]
                    cursor.execute("""
                        UPDATE manga SET
                            title = ?, url = ?, site_type = ?,
                            description = CASE WHEN ? != '' THEN ? ELSE description END,
                            author = CASE WHEN ? != '' THEN ? ELSE author END,
                            genres = CASE WHEN ? != '[]' THEN ? ELSE genres END,
                            status = CASE WHEN ? NOT IN ('', 'unknown') THEN ? ELSE status END,
                            release_date = CASE WHEN ? != '' THEN ? ELSE release_date END,
                            alternative_names = CASE WHEN ? != '[]' THEN ? ELSE alternative_names END,
                            cover_image_url = CASE WHEN ? != '' THEN ? ELSE cover_image_url END,
                            cover_image_path = CASE WHEN ? != '' THEN ? ELSE cover_image_path END,
                            translation_type = ?,
                            last_updated = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        metadata.title, metadata.url, metadata.site_type,
                        metadata.description, metadata.description,
                        metadata.author, metadata.author,
                        genres_json, genres_json,
                        metadata.status, metadata.status,
                        metadata.release_date, metadata.release_date,
                        alt_names_json, alt_names_json,
                        metadata.cover_image_url, metadata.cover_image_url,
                        cover_image_path, cover_image_path,
                        metadata.translation_type,
                        metadata.last_updated or datetime.now().isoformat(),
                        manga_id,
                    ))
                else:
                    now = datetime.now().isoformat()
                    cursor.execute("""
                        INSERT INTO manga
                        (title, url, site_type, description, author, genres, status,
                         release_date, alternative_names, cover_image_url, cover_image_path,
                         language, translation_type, first_download, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        metadata.title, metadata.url, metadata.site_type, metadata.description,
                        metadata.author, genres_json, metadata.status, metadata.release_date,
                        alt_names_json, metadata.cover_image_url, cover_image_path,
                        metadata.language, metadata.translation_type,
                        metadata.first_download or now, metadata.last_updated or now,
                    ))
                    manga_id = cursor.lastrowid

                conn.commit()
                return manga_id or 0

        except Exception as e:
            logging.error(f"Error adding/updating manga {metadata.title}: {e}")
            raise

    def add_or_update_chapter(self, manga_id: int, chapter_data: ChapterData):
        """Add or update a single chapter, keeping the row (and its ID) if it exists."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE chapters SET chapter_name = ?, chapter_url = ?, volume_number = ?,
                                        is_downloaded = ?, download_date = ?, file_path = ?
                    WHERE manga_id = ? AND chapter_number = ? AND language = ?
                """, (
                    chapter_data.chapter_name, chapter_data.chapter_url, chapter_data.volume_number,
                    chapter_data.is_downloaded, chapter_data.download_date, chapter_data.file_path,
                    manga_id, chapter_data.chapter_number, chapter_data.language,
                ))
                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO chapters
                        (manga_id, chapter_number, chapter_name, chapter_url, language, volume_number,
                         is_downloaded, download_date, file_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        manga_id, chapter_data.chapter_number, chapter_data.chapter_name,
                        chapter_data.chapter_url, chapter_data.language, chapter_data.volume_number,
                        chapter_data.is_downloaded, chapter_data.download_date, chapter_data.file_path,
                    ))
                conn.commit()

        except Exception as e:
            logging.error(f"Error adding/updating chapter {chapter_data.chapter_number}: {e}")
            raise

    def merge_chapters(self, manga_id: int, chapters: List[ChapterData], mark_new: bool = False) -> List[ChapterData]:
        """Insert chapters that are not stored yet and refresh name/URL of known ones.

        Download state of existing chapters is never touched. Returns the
        chapters that were newly inserted.
        """
        inserted: List[ChapterData] = []
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                for ch in chapters:
                    cursor.execute("""
                        INSERT OR IGNORE INTO chapters
                        (manga_id, chapter_number, chapter_name, chapter_url, language, volume_number, is_new, free_at,
                         group_name, group_locked, sources)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (manga_id, ch.chapter_number, ch.chapter_name, ch.chapter_url,
                          ch.language, ch.volume_number, 1 if mark_new else 0, ch.free_at,
                          ch.group_name, int(ch.group_locked), ch.sources))
                    if cursor.rowcount:
                        inserted.append(ch)
                    else:
                        cursor.execute("""
                            UPDATE chapters SET chapter_name = ?, chapter_url = ?, free_at = ?,
                                   volume_number = CASE WHEN ? != '' THEN ? ELSE volume_number END,
                                   group_name = ?, group_locked = ?, sources = ?
                            WHERE manga_id = ? AND chapter_number = ? AND language = ?
                        """, (ch.chapter_name, ch.chapter_url, ch.free_at, ch.volume_number, ch.volume_number,
                              ch.group_name, int(ch.group_locked), ch.sources,
                              manga_id, ch.chapter_number, ch.language))
                conn.commit()
        except Exception as e:
            logging.error(f"Error merging chapters for manga ID {manga_id}: {e}")
            raise
        return inserted

    def remove_missing_chapters(self, manga_id: int, keep: set) -> int:
        """Delete chapters that are not downloaded and no longer listed on the site.
        `keep` holds (language, chapter_number) of everything the site lists. Returns the count."""
        try:
            with self._connect() as conn:
                rows = conn.execute('SELECT id, language, chapter_number FROM chapters '
                                    'WHERE manga_id = ? AND is_downloaded = 0', (manga_id,)).fetchall()
                gone = [r[0] for r in rows if (r[1], r[2]) not in keep]
                conn.executemany('DELETE FROM chapters WHERE id = ?', [(i,) for i in gone])
                conn.commit()
                return len(gone)
        except Exception as e:
            logging.error(f"Error removing missing chapters for manga ID {manga_id}: {e}")
            return 0

    def set_chapter_sources(self, manga_id: int, changes: List[tuple]) -> None:
        """Switch chapters to another group's upload.
        changes: (language, chapter_number, url, group_name, locked, name, volume) per chapter."""
        try:
            with self._connect() as conn:
                conn.executemany("""
                    UPDATE chapters SET chapter_url = ?, group_name = ?, group_locked = ?,
                           chapter_name = CASE WHEN ? != '' THEN ? ELSE chapter_name END,
                           volume_number = CASE WHEN ? != '' THEN ? ELSE volume_number END
                    WHERE manga_id = ? AND chapter_number = ? AND language = ?
                """, [(url, group, int(locked), name, name, volume, volume, manga_id, number, language)
                      for language, number, url, group, locked, name, volume in changes])
                conn.commit()
        except Exception as e:
            logging.error(f"Error changing release groups of manga ID {manga_id}: {e}")

    def set_preferred_group(self, manga_id: int, group_name: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute('UPDATE manga SET preferred_group = ? WHERE id = ?', (group_name or '', manga_id))
                conn.commit()
        except Exception as e:
            logging.error(f"Error setting the release group of manga ID {manga_id}: {e}")

    def update_manga_description(self, manga_id: int, description: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute('UPDATE manga SET description = ? WHERE id = ?', (description, manga_id))
                conn.commit()
        except Exception as e:
            logging.error(f"Error updating description for manga ID {manga_id}: {e}")

    def clear_new_flags(self, manga_id: int) -> None:
        """Mark all chapters of a manga as seen."""
        try:
            with self._connect() as conn:
                conn.execute('UPDATE chapters SET is_new = 0 WHERE manga_id = ? AND is_new = 1', (manga_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Error clearing new flags for manga ID {manga_id}: {e}")

    def set_last_checked(self, manga_id: int, when: Optional[str] = None) -> None:
        """Remember when a manga was last checked for new chapters."""
        try:
            with self._connect() as conn:
                conn.execute('UPDATE manga SET last_checked = ? WHERE id = ?',
                             (when or datetime.now().isoformat(), manga_id))
                conn.commit()
        except Exception as e:
            logging.error(f"Error setting last_checked for manga ID {manga_id}: {e}")

    def merge_manga(self, keep_id: int, drop_id: int) -> None:
        """Fold a duplicate manga entry into another one, keeping every download state.
        Chapters only the duplicate knows are moved over; for shared chapters the
        downloaded flag/file path is carried over when the kept entry lacks it."""
        try:
            with self._connect() as conn:
                rows = conn.execute('''
                    SELECT chapter_number, language, chapter_name, chapter_url, volume_number,
                           is_downloaded, download_date, file_path
                    FROM chapters WHERE manga_id = ?
                ''', (drop_id,)).fetchall()
                for number, language, name, url, volume, downloaded, date, path in rows:
                    existing = conn.execute(
                        'SELECT is_downloaded FROM chapters WHERE manga_id = ? AND chapter_number = ? AND language = ?',
                        (keep_id, number, language)).fetchone()
                    if existing is None:
                        conn.execute('''
                            INSERT INTO chapters (manga_id, chapter_number, chapter_name, chapter_url, language,
                                                  volume_number, is_downloaded, download_date, file_path)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (keep_id, number, name, url, language, volume, downloaded, date, path))
                    elif downloaded and not existing[0]:
                        conn.execute('''
                            UPDATE chapters SET is_downloaded = 1, download_date = ?, file_path = ?
                            WHERE manga_id = ? AND chapter_number = ? AND language = ?
                        ''', (date, path, keep_id, number, language))
                conn.execute('DELETE FROM chapters WHERE manga_id = ?', (drop_id,))
                conn.execute('DELETE FROM manga WHERE id = ?', (drop_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Error merging manga {drop_id} into {keep_id}: {e}")

    def update_manga_url(self, manga_id: int, url: str, site_type: Optional[str] = None) -> None:
        """Point a manga at a new source link (e.g. after the site moved domains)."""
        try:
            with self._connect() as conn:
                if site_type:
                    conn.execute('UPDATE manga SET url = ?, site_type = ? WHERE id = ?', (url, site_type, manga_id))
                else:
                    conn.execute('UPDATE manga SET url = ? WHERE id = ?', (url, manga_id))
                conn.commit()
        except Exception as e:
            logging.error(f"Error updating URL for manga ID {manga_id}: {e}")

    def delete_manga_by_id(self, manga_id: int) -> None:
        """Delete a manga and its chapters from the database (files stay on disk)."""
        try:
            with self._connect() as conn:
                conn.execute('DELETE FROM chapters WHERE manga_id = ?', (manga_id,))
                conn.execute('DELETE FROM manga WHERE id = ?', (manga_id,))
                conn.commit()
        except Exception as e:
            logging.error(f"Error deleting manga ID {manga_id}: {e}")

    def get_manga_list(self) -> List[Dict[str, Any]]:
        """Get list of all manga with basic info."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT m.id, m.title, m.url, m.site_type, m.description, m.author, m.genres,
                           m.status, m.cover_image_path, m.last_updated, m.first_download,
                           COUNT(DISTINCT c.chapter_number) as total_chapters,
                           COUNT(DISTINCT CASE WHEN c.is_downloaded = 1 THEN c.chapter_number END) as downloaded_chapters,
                           COUNT(DISTINCT CASE WHEN c.is_new = 1 AND c.is_downloaded = 0 THEN c.chapter_number END) as new_chapters,
                           m.last_checked, m.language,
                           MAX(c.created_at) as latest_chapter_at
                    FROM manga m
                    LEFT JOIN chapters c ON m.id = c.manga_id
                    GROUP BY m.id, m.title
                    ORDER BY m.last_updated DESC
                ''')
                
                results = cursor.fetchall()
                manga_list = []
                
                for row in results:
                    genres = json.loads(row[6]) if row[6] else []
                    manga_list.append({
                        'id': row[0],
                        'title': row[1],
                        'url': row[2],
                        'site_type': row[3],
                        'description': row[4],
                        'author': row[5],
                        'genres': genres,
                        'status': row[7],
                        'cover_image_path': row[8],
                        'last_updated': row[9],
                        'first_download': row[10],
                        'total_chapters': row[11],
                        'downloaded_chapters': row[12],
                        'new_chapters': row[13],
                        'last_checked': row[14] or '',
                        'language': row[15] or 'en',
                        'latest_chapter_at': row[16] or '',   # when the newest chapter was found
                    })
                
                return manga_list
                
        except Exception as e:
            logging.error(f"Error getting manga list: {e}")
            return []
    
    def get_manga_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Get manga data by title."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT id, title, url, site_type, description, author, genres, status,
                           release_date, alternative_names, cover_image_url, cover_image_path,
                           first_download, last_updated
                    FROM manga WHERE title = ?
                ''', (title,))
                
                result = cursor.fetchone()
                if not result:
                    return None
                
                return {
                    'id': result[0],
                    'title': result[1],
                    'url': result[2],
                    'site_type': result[3],
                    'description': result[4],
                    'author': result[5],
                    'genres': json.loads(result[6]) if result[6] else [],
                    'status': result[7],
                    'release_date': result[8],
                    'alternative_names': json.loads(result[9]) if result[9] else [],
                    'cover_image_url': result[10],
                    'cover_image_path': result[11],
                    'first_download': result[12],
                    'last_updated': result[13]
                }
                
        except Exception as e:
            logging.error(f"Error getting manga {title}: {e}")
            return None
    
    def get_manga_by_id(self, manga_id: int) -> Optional[Dict[str, Any]]:
        """Get manga data by ID."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT id, title, url, site_type, description, author, genres, status,
                           release_date, alternative_names, cover_image_url, cover_image_path,
                           first_download, last_updated, last_page_scanned, total_pages, 
                           last_chapter_scan, chapters_cached, preferred_group
                    FROM manga WHERE id = ?
                ''', (manga_id,))
                
                result = cursor.fetchone()
                if not result:
                    return None
                
                return {
                    'id': result[0],
                    'title': result[1],
                    'url': result[2],
                    'site_type': result[3],
                    'description': result[4],
                    'author': result[5],
                    'genres': json.loads(result[6]) if result[6] else [],
                    'status': result[7],
                    'release_date': result[8],
                    'alternative_names': json.loads(result[9]) if result[9] else [],
                    'cover_image_url': result[10],
                    'cover_image_path': result[11],
                    'first_download': result[12],
                    'last_updated': result[13],
                    'last_page_scanned': result[14] if len(result) > 14 else 0,
                    'total_pages': result[15] if len(result) > 15 else 0,
                    'last_chapter_scan': result[16] if len(result) > 16 else '',
                    'chapters_cached': result[17] if len(result) > 17 else 0,
                    'preferred_group': result[18] or '',
                }
                
        except Exception as e:
            logging.error(f"Error getting manga by ID {manga_id}: {e}")
            return None
    
    def get_manga_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Get manga data by URL."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT id, title, url, site_type, description, author, genres, status,
                           release_date, alternative_names, cover_image_url, cover_image_path,
                           first_download, last_updated, last_page_scanned, total_pages, 
                           last_chapter_scan, chapters_cached, preferred_group
                    FROM manga WHERE url = ?
                ''', (url,))
                
                result = cursor.fetchone()
                if not result:
                    return None
                
                return {
                    'id': result[0],
                    'title': result[1],
                    'url': result[2],
                    'site_type': result[3],
                    'description': result[4],
                    'author': result[5],
                    'genres': json.loads(result[6]) if result[6] else [],
                    'status': result[7],
                    'release_date': result[8],
                    'alternative_names': json.loads(result[9]) if result[9] else [],
                    'cover_image_url': result[10],
                    'cover_image_path': result[11],
                    'first_download': result[12],
                    'last_updated': result[13],
                    'last_page_scanned': result[14] if len(result) > 14 else 0,
                    'total_pages': result[15] if len(result) > 15 else 0,
                    'last_chapter_scan': result[16] if len(result) > 16 else '',
                    'chapters_cached': result[17] if len(result) > 17 else 0,
                    'preferred_group': result[18] or '',
                }
                
        except Exception as e:
            logging.error(f"Error getting manga by URL {url}: {e}")
            return None
    
    def get_chapters_for_manga(self, manga_id: int, include_not_downloaded: bool = True, language: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all chapters for a manga, optionally filtered by language."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                query = '''
                    SELECT chapter_number, chapter_name, chapter_url, language, volume_number, is_downloaded, 
                           download_date, file_path, is_new, free_at, group_name, group_locked, sources
                    FROM chapters 
                    WHERE manga_id = ?
                '''
                params: list = [manga_id]
                
                if not include_not_downloaded:
                    query += ' AND is_downloaded = 1'
                
                if language:
                    query += ' AND language = ?'
                    params.append(language)
                
                query += ' ORDER BY CAST(chapter_number AS REAL), chapter_number'
                
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                chapters = []
                for row in results:
                    chapters.append({
                        'chapter_number': row[0],
                        'chapter_name': row[1],
                        'chapter_url': row[2],
                        'language': row[3],
                        'volume_number': row[4],
                        'is_downloaded': bool(row[5]),
                        'download_date': row[6],
                        'file_path': row[7],
                        'is_new': bool(row[8]),
                        'free_at': row[9] or '',
                        'group_name': row[10] or '',
                        'group_locked': bool(row[11]),
                        'sources': row[12] or '',
                    })
                
                return chapters
                
        except Exception as e:
            logging.error(f"Error getting chapters for manga ID {manga_id}: {e}")
            return []
    
    def mark_chapter_downloaded(self, manga_id: int, chapter_number: str, file_path: str = "", language: Optional[str] = None):
        """Mark a chapter as downloaded, optionally scoped to a specific language."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                if language:
                    cursor.execute('''
                        UPDATE chapters 
                        SET is_downloaded = 1, download_date = ?, file_path = ?
                        WHERE manga_id = ? AND chapter_number = ? AND language = ?
                    ''', (datetime.now().isoformat(), file_path, manga_id, chapter_number, language))
                else:
                    cursor.execute('''
                        UPDATE chapters 
                        SET is_downloaded = 1, download_date = ?, file_path = ?
                        WHERE manga_id = ? AND chapter_number = ?
                    ''', (datetime.now().isoformat(), file_path, manga_id, chapter_number))
                
                conn.commit()
                
        except Exception as e:
            logging.error(f"Error marking chapter {chapter_number} as downloaded: {e}")
    
    def reset_chapter_download_status(self, manga_id: int, chapter_number: str, language: Optional[str] = None):
        """Reset a chapter's download status to allow redownloading, optionally scoped to a language."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                if language:
                    cursor.execute('''
                        UPDATE chapters 
                        SET is_downloaded = 0, download_date = NULL, file_path = NULL
                        WHERE manga_id = ? AND chapter_number = ? AND language = ?
                    ''', (manga_id, chapter_number, language))
                else:
                    cursor.execute('''
                        UPDATE chapters 
                        SET is_downloaded = 0, download_date = NULL, file_path = NULL
                        WHERE manga_id = ? AND chapter_number = ?
                    ''', (manga_id, chapter_number))
                
                conn.commit()
                logging.info(f"Reset download status for chapter {chapter_number}" + (f" [{language}]" if language else ""))
                
        except Exception as e:
            logging.error(f"Error resetting chapter {chapter_number} download status: {e}")
    
    def update_cover_image_path(self, manga_id: int, cover_path: str):
        """Update the local cover image path for a manga."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE manga SET cover_image_path = ? WHERE id = ?
                ''', (cover_path, manga_id))
                
                conn.commit()
                
        except Exception as e:
            logging.error(f"Error updating cover path for manga ID {manga_id}: {e}")
    
    def delete_manga(self, title: str):
        """Delete a manga and all its chapters."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('DELETE FROM chapters WHERE manga_id IN (SELECT id FROM manga WHERE title = ?)', (title,))
                cursor.execute('DELETE FROM manga WHERE title = ?', (title,))
                conn.commit()
                
        except Exception as e:
            logging.error(f"Error deleting manga {title}: {e}")
    
    def search_manga(self, query: str) -> List[Dict[str, Any]]:
        """Search manga by title, author, or genre."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT m.id, m.title, m.site_type, m.description, m.author, m.genres,
                           m.status, m.cover_image_path, m.last_updated,
                           COUNT(c.id) as total_chapters,
                           COUNT(CASE WHEN c.is_downloaded = 1 THEN 1 END) as downloaded_chapters
                    FROM manga m
                    LEFT JOIN chapters c ON m.id = c.manga_id
                    WHERE m.title LIKE ? OR m.author LIKE ? OR m.genres LIKE ?
                    GROUP BY m.id, m.title
                    ORDER BY m.last_updated DESC
                ''', (f'%{query}%', f'%{query}%', f'%{query}%'))
                
                results = cursor.fetchall()
                manga_list = []
                
                for row in results:
                    genres = json.loads(row[5]) if row[5] else []
                    manga_list.append({
                        'id': row[0],
                        'title': row[1],
                        'site_type': row[2],
                        'description': row[3],
                        'author': row[4],
                        'genres': genres,
                        'status': row[6],
                        'cover_image_path': row[7],
                        'last_updated': row[8],
                        'total_chapters': row[9],
                        'downloaded_chapters': row[10]
                    })
                
                return manga_list
                
        except Exception as e:
            logging.error(f"Error searching manga with query '{query}': {e}")
            return []