"""
Metadata manager for handling manga metadata updates and backfill operations.
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .database_manager import DatabaseManager, MangaMetadata, ChapterData


class MetadataManager:
    """Manager for metadata operations including backfill for existing manga."""
    
    def __init__(self, download_manager=None):
        self.db_manager = DatabaseManager()
        self.download_manager = download_manager
        self.cover_images_dir = os.path.join(os.path.expanduser("~"), ".mangadownloader", "covers")
        os.makedirs(self.cover_images_dir, exist_ok=True)
    
    def needs_metadata_update(self, manga_data: Dict) -> bool:
        """Check if a manga entry needs metadata update."""
        if not manga_data.get('url') or manga_data['url'].strip() == "":
            return False
        
        missing_author = not manga_data.get('author') or manga_data['author'].strip() == ""
        missing_description = not manga_data.get('description') or manga_data['description'].strip() == ""
        missing_genres = not manga_data.get('genres') or len(manga_data['genres']) == 0
        missing_cover = not manga_data.get('cover_image_path') or not os.path.exists(manga_data.get('cover_image_path', ''))
        
        return missing_author or missing_description or missing_genres or missing_cover
    
    def refresh_manga_metadata(self, manga_id: int, force_refresh: bool = False) -> bool:
        """Refresh metadata for a specific manga."""
        try:
            if not self.download_manager:
                logging.warning("No download manager available for metadata refresh")
                return False
            
            manga_list = self.db_manager.get_manga_list()
            manga_data = None
            for manga in manga_list:
                if manga['id'] == manga_id:
                    manga_data = manga
                    break
            
            if not manga_data:
                logging.error(f"Manga with ID {manga_id} not found")
                return False
            
            if not force_refresh and not self.needs_metadata_update(manga_data):
                logging.info(f"Manga '{manga_data['title']}' metadata is already complete")
                return True
            
            downloader = self.download_manager.get_site_downloader(manga_data['url'])
            if not downloader:
                logging.error(f"No downloader found for URL: {manga_data['url']}")
                return False
            
            site_metadata = downloader.get_manga_metadata(manga_data['url'])
            
            cover_image_path = manga_data.get('cover_image_path', '')
            if site_metadata.cover_image_url and (
                not cover_image_path or 
                not os.path.exists(cover_image_path) or
                force_refresh
            ):
                cover_image_path = self.download_manager.download_cover_image(
                    site_metadata.cover_image_url, 
                    manga_data['title']
                )
            
            updated_metadata = MangaMetadata(
                title=manga_data['title'],
                url=manga_data['url'],
                site_type=manga_data['site_type'],
                description=site_metadata.description or manga_data.get('description', ''),
                author=site_metadata.author or manga_data.get('author', ''),
                genres=site_metadata.genres if site_metadata.genres else manga_data.get('genres', []),
                status=site_metadata.status or manga_data.get('status', 'unknown'),
                release_date=site_metadata.release_date or manga_data.get('release_date', ''),
                alternative_names=site_metadata.alternative_names if site_metadata.alternative_names else manga_data.get('alternative_names', []),
                cover_image_url=site_metadata.cover_image_url or manga_data.get('cover_image_url', ''),
                language=getattr(site_metadata, 'language', manga_data.get('language', 'en')),
                translation_type=getattr(site_metadata, 'translation_type', manga_data.get('translation_type', 'official')),
                last_updated=datetime.now().isoformat(),
                first_download=manga_data.get('first_download', datetime.now().isoformat())
            )
            
            self.db_manager.add_or_update_manga(updated_metadata, cover_image_path)
            
            existing_chapters = self.db_manager.get_chapters_for_manga(manga_id)
            
            try:
                chapters = downloader.get_chapter_links(manga_data['url'])
                chapter_dict = {ch[0]: ch[1] for ch in chapters}
                
                for chapter in existing_chapters:
                    chapter_num = chapter['chapter_number']
                    current_name = chapter['chapter_name']
                    
                    if (current_name.startswith("Chapter ") and 
                        chapter_num in chapter_dict and 
                        chapter_dict[chapter_num] != current_name):
                        
                        updated_chapter = ChapterData(
                            chapter_number=chapter_num,
                            chapter_name=chapter_dict[chapter_num],
                            chapter_url=chapter['chapter_url'],
                            language=chapter['language'],
                            is_downloaded=chapter['is_downloaded'],
                            download_date=chapter['download_date'],
                            file_path=chapter['file_path']
                        )
                        self.db_manager.add_or_update_chapter(manga_id, updated_chapter)
                        
            except Exception as e:
                logging.warning(f"Could not update chapter names for {manga_data['title']}: {e}")
            
            logging.info(f"Successfully refreshed metadata for '{manga_data['title']}'")
            return True
            
        except Exception as e:
            logging.error(f"Error refreshing metadata for manga ID {manga_id}: {e}")
            return False
    
    def backfill_all_metadata(self, progress_callback=None) -> Tuple[int, int]:
        """Backfill metadata for all manga that need updates."""
        if not self.download_manager:
            raise ValueError("Download manager required for metadata backfill")
        
        manga_list = self.db_manager.get_manga_list()
        needs_update = []
        
        for manga in manga_list:
            if self.needs_metadata_update(manga):
                needs_update.append(manga)
        
        if not needs_update:
            logging.info("No manga need metadata updates")
            return 0, 0
        
        successful_updates = 0
        
        for i, manga in enumerate(needs_update):
            try:
                if progress_callback:
                    progress_callback(i + 1, len(needs_update), manga['title'])
                
                if self.refresh_manga_metadata(manga['id']):
                    successful_updates += 1
                    logging.info(f"Updated metadata for '{manga['title']}' ({i+1}/{len(needs_update)})")
                else:
                    logging.warning(f"Failed to update metadata for '{manga['title']}'")
                    
            except Exception as e:
                logging.error(f"Error updating metadata for '{manga['title']}': {e}")
        
        return successful_updates, len(needs_update)
    
    def get_manga_needing_updates(self) -> List[Dict]:
        """Get list of manga that need metadata updates."""
        manga_list = self.db_manager.get_manga_list()
        return [manga for manga in manga_list if self.needs_metadata_update(manga)]
    
    def merge_and_update_metadata(self, manga_data: Dict, new_metadata: Dict) -> Dict:
        """Merge existing manga data with new metadata, prioritizing non-empty values."""
        merged = manga_data.copy()
        
        if new_metadata.get('author') and new_metadata['author'].strip():
            merged['author'] = new_metadata['author']
        
        if new_metadata.get('description') and new_metadata['description'].strip():
            merged['description'] = new_metadata['description']
        
        if new_metadata.get('genres') and len(new_metadata['genres']) > 0:
            merged['genres'] = new_metadata['genres']
        
        if new_metadata.get('status') and new_metadata['status'] != 'unknown':
            merged['status'] = new_metadata['status']
        
        if new_metadata.get('cover_image_url'):
            merged['cover_image_url'] = new_metadata['cover_image_url']
        
        if new_metadata.get('cover_image_path') and os.path.exists(new_metadata['cover_image_path']):
            merged['cover_image_path'] = new_metadata['cover_image_path']
        
        merged['last_updated'] = datetime.now().isoformat()
        
        return merged