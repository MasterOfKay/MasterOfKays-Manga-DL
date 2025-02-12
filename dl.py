from assuracomics import get_chapter_links as asura_get_chapter_links
from assuracomics import download_chapter as asura_download_chapter
from assuracomics import get_manga_name as asura_get_manga_name
from mangakatana import get_chapter_links as katana_get_chapter_links
from mangakatana import download_chapter as katana_download_chapter
from mangakatana import get_manga_name as katana_get_manga_name
import re
from typing import Optional, Tuple, List
import os

def validate_manga_url(url: str) -> Tuple[bool, str]:
    """Validate if the URL is a supported manga URL and return the site type"""
    asura_pattern = r'^https?://asuracomic\.net/series/[a-zA-Z0-9-_]+/?$'
    katana_pattern = r'^https?://mangakatana\.com/manga/[a-zA-Z0-9-_.]+/?$'
    
    if re.match(asura_pattern, url):
        return True, "asura"
    elif re.match(katana_pattern, url):
        return True, "katana"
    return False, ""

def parse_chapter_range(range_str: Optional[str]) -> Tuple[float, float]:
    """Parse chapter range string (e.g., '5' or '0-20')"""
    if not range_str:
        return (0, float('inf'))
    
    parts = range_str.strip().split('-')
    try:
        if len(parts) == 1:
            start = float(parts[0])
            return (start, start)
        elif len(parts) == 2:
            start = float(parts[0])
            end = float(parts[1])
            return (start, end)
        else:
            raise ValueError
    except ValueError:
        print("Invalid range format. Using all chapters.")
        return (0, float('inf'))

def download_chapters(chapters: List[Tuple[str, str, str]], manga_name: str, site_type: str):
    """Download selected chapters and create CBZ files"""
    response = input("\nDo you want to download the selected chapters? (y/n): ").strip().lower()
    
    if response != 'y':
        print("Download cancelled.")
        return

    print(f"\nPreparing to download {len(chapters)} chapter(s)...")
    for chapter_num, _, chapter_url in chapters:
        print(f"\nProcessing Chapter {chapter_num}")
        if site_type == "asura":
            cbz_file = asura_download_chapter(chapter_url, chapter_num, manga_name)
        else:  # site_type == "katana"
            cbz_file = katana_download_chapter(chapter_url, chapter_num, manga_name)
        
        if cbz_file:
            rel_path = os.path.relpath(cbz_file)
            print(f"Created: {rel_path}")

def main():
    print("Please paste the manga URL (optionally followed by chapter range, e.g., 'URL 0-20'):")
    user_input = input().strip().split(None, 1)
    url = user_input[0]
    chapter_range = user_input[1] if len(user_input) > 1 else None

    is_valid, site_type = validate_manga_url(url)
    if not is_valid:
        print("Error: Unsupported website. Currently supported: asuracomic.net, mangakatana.com")
        return

    print("\nFetching chapters...")
    if site_type == "asura":
        chapters = asura_get_chapter_links(url)
        manga_name = asura_get_manga_name(url)
    else:  # site_type == "katana"
        chapters = katana_get_chapter_links(url)
        manga_name = katana_get_manga_name(url)

    if chapters:
        start_ch, end_ch = parse_chapter_range(chapter_range)
        filtered_chapters = [
            (num, name, link) for num, name, link in chapters
            if start_ch <= float(num.replace(',', '')) <= end_ch
        ]
        
        if filtered_chapters:
            print(f"\nFound {len(filtered_chapters)} chapters in range for: {url}\n")
            print("=" * 120)
            for chapter_num, chapter_name, link in filtered_chapters:
                formatted_chapter = f"Chapter {chapter_num.strip()}"
                print(f"{formatted_chapter:<20} | {chapter_name:<50} | {link}")
            print("=" * 120)
            
            download_chapters(filtered_chapters, manga_name, site_type)
        else:
            print(f"No chapters found in range {start_ch}-{end_ch}")
    else:
        print("No chapters found or error occurred")

if __name__ == "__main__":
    main()
