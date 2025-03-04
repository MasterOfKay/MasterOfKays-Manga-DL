"""
Enhanced version of dl.py with a simple menu interface
Uses only standard libraries and the same functionality as the original dl.py
"""

import os
import sys
import re
from typing import Optional, Tuple, List

from assuracomics import get_chapter_links as asura_get_chapter_links
from assuracomics import download_chapter as asura_download_chapter
from assuracomics import get_manga_name as asura_get_manga_name
from mangakatana import get_chapter_links as katana_get_chapter_links
from mangakatana import download_chapter as katana_download_chapter
from mangakatana import get_manga_name as katana_get_manga_name
from webtoon import get_chapter_links as webtoon_get_chapter_links
from webtoon import download_chapter as webtoon_download_chapter
from webtoon import get_manga_name as webtoon_get_manga_name

def clear_screen():
    """Clear the console screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    """Print the application header"""
    clear_screen()
    print("=" * 60)
    print("MANGA DOWNLOADER".center(60))
    print("=" * 60)
    print("Supported sites: AsuraScans, MangaKatana, Webtoon".center(60))
    print("=" * 60)
    print()

def validate_manga_url(url: str) -> Tuple[bool, str]:
    """Validate if the URL is a supported manga URL and return the site type"""
    asura_pattern = r'^https?://asuracomic\.net/series/[a-zA-Z0-9-_]+/?$'
    katana_pattern = r'^https?://mangakatana\.com/manga/[a-zA-Z0-9-_.]+/?$'
    webtoon_pattern = r'^https?://www\.webtoons\.com/[a-z]{2}/[^/]+/[^/]+/list\?title_no=\d+$'
    
    if re.match(asura_pattern, url):
        return True, "asura"
    elif re.match(katana_pattern, url):
        return True, "katana"
    elif re.match(webtoon_pattern, url):
        return True, "webtoon"
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
    print(f"\nPreparing to download {len(chapters)} chapter(s)...")
    
    for idx, (chapter_num, chapter_name, chapter_url) in enumerate(chapters, 1):
        print(f"\n[{idx}/{len(chapters)}] Processing Chapter {chapter_num}")
        if site_type == "asura":
            cbz_file = asura_download_chapter(chapter_url, chapter_num, manga_name)
        elif site_type == "katana":
            cbz_file = katana_download_chapter(chapter_url, chapter_num, manga_name)
        else:
            cbz_file = webtoon_download_chapter(chapter_url, chapter_num, manga_name)
        
        if cbz_file:
            rel_path = os.path.relpath(cbz_file)
            print(f"Created: {rel_path}")

def show_chapter_selection_menu(chapters: List[Tuple[str, str, str]], manga_name: str):
    """Show a menu for chapter selection"""
    while True:
        clear_screen()
        print(f"MANGA: {manga_name}")
        print(f"Found {len(chapters)} chapters\n")
        
        print("Select option:")
        print("1. Download all chapters")
        print("2. Download specific chapter")
        print("3. Download range of chapters")
        print("4. List chapters")
        print("0. Return to main menu")
        
        choice = input("\nEnter choice (0-4): ").strip()
        
        if choice == "0":
            return None
        elif choice == "1":
            return chapters
        elif choice == "2":
            try:
                while True:
                    print("\nEnter chapter number (example: for Chapter 42, enter 42):")
                    chapter_num = input("> ").strip()
                    
                    matching_chapters = [c for c in chapters if c[0] == chapter_num]
                    
                    if matching_chapters:
                        return matching_chapters
                    else:
                        print(f"Chapter {chapter_num} not found.")
                        if input("Try again? (y/n): ").lower() != 'y':
                            break
            except ValueError:
                print("Invalid chapter number.")
                input("Press Enter to continue...")
        elif choice == "3":
            try:
                print("\nEnter chapter range (e.g., 1-10):")
                range_input = input("> ").strip()
                start_ch, end_ch = parse_chapter_range(range_input)
                
                filtered_chapters = [
                    (num, name, link) for num, name, link in chapters
                    if start_ch <= float(num.replace(',', '')) <= end_ch
                ]
                
                if filtered_chapters:
                    print(f"\nSelected {len(filtered_chapters)} chapters in range {start_ch}-{end_ch}")
                    input("Press Enter to continue...")
                    return filtered_chapters
                else:
                    print(f"No chapters found in range {start_ch}-{end_ch}")
                    input("Press Enter to continue...")
            except ValueError:
                print("Invalid range format.")
                input("Press Enter to continue...")
        elif choice == "4":
            page_size = 20
            total_pages = (len(chapters) + page_size - 1) // page_size
            current_page = 0
            
            while True:
                clear_screen()
                print(f"MANGA: {manga_name} - Chapter List")
                print(f"Page {current_page + 1} of {total_pages}\n")
                
                start_idx = current_page * page_size
                end_idx = min(start_idx + page_size, len(chapters))
                
                for i, (chapter_num, chapter_name, _) in enumerate(chapters[start_idx:end_idx], start_idx + 1):
                    print(f"{i}. Chapter {chapter_num}: {chapter_name}")
                
                print("\nCommands:")
                print("  n - next page")
                print("  p - previous page")
                print("  b - back to selection menu")
                
                cmd = input("\nEnter command: ").strip().lower()
                
                if cmd == 'n' and current_page < total_pages - 1:
                    current_page += 1
                elif cmd == 'p' and current_page > 0:
                    current_page -= 1
                elif cmd == 'b':
                    break

def main():
    """Main application flow"""
    while True:
        print_header()
        print("Select option:")
        print("1. Download manga")
        print("2. About")
        print("0. Exit")
        
        choice = input("\nEnter choice (0-2): ").strip()
        
        if choice == "0":
            print("\nThank you for using Manga Downloader!")
            break
        
        elif choice == "1":
            print_header()
            print("Enter manga URL:")
            url = input("> ").strip()
            
            is_valid, site_type = validate_manga_url(url)
            if not is_valid:
                print("\nError: Unsupported website.")
                print("Currently supported sites: asuracomic.net, mangakatana.com, webtoons.com")
                input("Press Enter to continue...")
                continue
            
            print("\nFetching chapters...")
            
            try:
                if site_type == "asura":
                    manga_name = asura_get_manga_name(url)
                    chapters = asura_get_chapter_links(url)
                elif site_type == "katana":
                    manga_name = katana_get_manga_name(url)
                    chapters = katana_get_chapter_links(url)
                else:
                    manga_name = webtoon_get_manga_name(url)
                    chapters = webtoon_get_chapter_links(url)
                
                if chapters:
                    selected_chapters = show_chapter_selection_menu(chapters, manga_name)
                    
                    if selected_chapters:
                        print(f"\nReady to download {len(selected_chapters)} chapters of '{manga_name}'.")
                        if input("Proceed? (y/n): ").lower() == 'y':
                            download_chapters(selected_chapters, manga_name, site_type)
                            print("\nDownload complete!")
                else:
                    print("No chapters found or error occurred")
            
            except Exception as e:
                print(f"Error: {e}")
            
            input("\nPress Enter to continue...")
        
        elif choice == "2":
            print_header()
            print("Manga Downloader")
            print("Version: 1.1.0")
            print("\nSupported Sites:")
            print("- AsuraScans (https://asuracomic.net)")
            print("- MangaKatana (https://mangakatana.com)")
            print("- Webtoon (https://www.webtoons.com)")
            print("\nThis tool downloads manga chapters as CBZ files for offline reading.")
            print("For personal use only. Please support the content creators.")
            input("\nPress Enter to continue...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        input("Press Enter to exit...")
