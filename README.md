Manga Downloader

This is a small side project to download mangas, currently supporting AssuraComics (MangaKatana comming soon TM). It’s written in Python, and for now, it’s just a simple script.

Features

✔ Download manga from AssuraComics
✔ Save chapters for offline reading

Future Plans (Maybe)
	•	Support for more sites
	•	A UI for easier use

This project is just for fun, and updates will happen if people want them or if I feel like it.

How to Use
	1.	Install dependencies:

pip install -r requirements.txt


	2.	Run the script:

python dl.py

    3. Insert the link for the Manga (The Main page not the chapter page). After the link you can specyfy wich chapter or chapters you want.

    Example:
    
    Download all:
    https://asuracomic.net/series/i-obtained-a-mythic-item-0af32371

    Download just one Chapter:
    https://asuracomic.net/series/i-obtained-a-mythic-item-0af32371 34

    Downloading just a span of Chapters
    https://asuracomic.net/series/i-obtained-a-mythic-item-0af32371 53-87

    This Script will then list all the chapters or just the selcted chepters, and will ask if you want to DL them (y/n). If yes it will start and will also create a Folder with the Name of the Manga.

Disclaimer

This tool is for personal use only. Please respect the rights of the content creators.

Feel free to open an issue or suggest features, but no promises on updates!