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
- ✔ Multi-language support for Webtoon

## Installation

1. Clone this repository or download the ZIP file
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the script:
```bash
python dl.py
```

### Download Examples

You will be prompted to enter a manga URL and optionally a chapter range. Here are some examples:

1. **Download all chapters:**
```
https://asuracomic.net/series/i-obtained-a-mythic-item
```
or
```
https://mangakatana.com/manga/my-gift-lvl-9999-unlimited-gacha
```
or
```
https://www.webtoons.com/de/romance/hot-guy-and-a-beast/list?title_no=4374
```

2. **Download a single chapter:**
```
https://asuracomic.net/series/i-obtained-a-mythic-item 34
```
This will download only chapter 34

3. **Download a range of chapters:**
```
https://www.webtoons.com/de/romance/hot-guy-and-a-beast/list?title_no=4374 5-10
```
This will download chapters 5 through 10

The script will then:
1. List all matching chapters
2. Ask for confirmation (y/n)
3. Create a folder with the manga name
4. Download each chapter as a CBZ file

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

- Python 3.6+
- Required packages (installed via requirements.txt):
  - requests
  - beautifulsoup4

## Disclaimer

This tool is for personal use only. Please support the content creators by purchasing official releases when available.

## Contributing

Feel free to:
- Report bugs via issues
- Suggest new features
- Submit pull requests

## License

This project is for educational purposes only. Use responsibly and respect copyright laws.