# Manga Downloader

A Python-based manga downloader that supports downloading from multiple manga sites for offline reading.

## Currently Supported Sites

- [AsuraScans](https://asuracomic.net)
- [MangaKatana](https://mangakatana.com)
- [Webtoon](https://www.webtoons.com)

## Features

- ✔ Download manga chapters from supported sites
- ✔ Save chapters as CBZ files for offline reading
- ✔ Selective chapter downloading (single, range, or all)
- ✔ Skip already downloaded chapters
- ✔ Multiple user interfaces (GUI and CLI)
- ✔ Download queue management
- ✔ Pause and resume downloads
- ✔ Multi-language support for Webtoon

## Installation

### Option 1: Download the Executable (Windows)

For Windows users, a standalone executable version of the GUI is included in the GitHub repository ZIP download. No Python installation required!

1. Download the ZIP from GitHub
2. Extract the files
3. Run `MangaDownloader.exe` to start the application

The executable version includes all required dependencies and works without any additional installation.

> **Note**: A standalone executable will also be available in GitHub Releases for easier access.

### Option 2: Install from Source

1. Clone this repository or download the ZIP file
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Quick Start

#### Using the Executable (Windows)
Simply double-click `MangaDownloader.exe` to launch the GUI version.

#### Using Python
Run the launcher script to automatically select the best available interface:
```bash
python run.py
```

### Available Interfaces

#### GUI Interface (manga_downloader_gui.py)

The GUI interface provides:
- Easy-to-use form for entering manga URLs
- Chapter selection dialog
- Download queue management
- Pause/resume functionality
- Chapter download progress tracking
- Chapter list viewer

```bash
python manga_downloader_gui.py
```

#### Enhanced CLI (enhanced_dl.py)

A menu-based CLI interface with:
- Interactive menu
- Chapter browser
- Download status display
- Range selection

```bash
python enhanced_dl.py
```

#### Basic CLI (dl.py)

Simple command-line interface for:
- Quick chapter downloads
- Batch processing

```bash
python dl.py
```

### Download Examples

#### GUI Mode
1. Enter the manga URL in the input field
2. Click "Download" button
3. Select chapters you want to download
4. Manage downloads from the queue

#### CLI Mode
Enter a manga URL and optionally a chapter range:

1. **Download all chapters:**
```
https://asuracomic.net/series/i-obtained-a-mythic-item
```

2. **Download a single chapter:**
```
https://asuracomic.net/series/i-obtained-a-mythic-item 34
```

3. **Download a range of chapters:**
```
https://www.webtoons.com/de/romance/hot-guy-and-a-beast/list?title_no=4374 5-10
```

### Output Structure

Downloads will be organized as follows:
```
Current Directory/
└── Manga Name/
    ├── Chapter 1.cbz
    ├── Chapter 2.cbz
    └── Chapter 3.cbz
```

## Requirements

### For Executable Version
- Windows operating system
- No additional requirements

### For Source Code Version
- Python 3.6+
- Required packages (installed via requirements.txt):
  - requests
  - beautifulsoup4
  - PyQt5 (for GUI version)
  - selenium (for certain sites)

## Building the Executable

You can build your own executable using PyInstaller:

```bash
python build_exe.py
```

Or using Auto-PY-to-EXE:

```bash
pip install auto-py-to-exe
auto-py-to-exe
```

## Disclaimer

This tool is for personal use only. Please support the content creators by purchasing official releases when available.

## Contributing

Feel free to:
- Report bugs via issues
- Suggest new features
- Submit pull requests

## License

This project is for educational purposes only. Use responsibly and respect copyright laws.