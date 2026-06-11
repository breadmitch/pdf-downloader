# Mining Report PDF Downloader

A simple Windows desktop utility for finding and downloading PDF links from public web pages.

This was designed for research workflows where a user needs to collect publicly available report PDFs, such as technical mining reports, from pages that list direct PDF links.

## Features

- Paste a webpage URL and scan for direct PDF links
- Select individual PDFs using checkboxes
- Check all / uncheck all PDF links
- Choose a local download folder
- Download selected PDFs locally
- Respect robots.txt checks before scanning and downloading
- Use a polite default crawl delay
- Verify downloaded files begin with a PDF header
- Skip files that already exist
- Create a `download_log.csv` with metadata including URL, file size, status, and SHA-256 hash

## Requirements for running from source

- Python 3.10 or newer
- Windows, macOS, or Linux
- Python packages listed in `requirements.txt`

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python app.py
```

## How to use

1. Open the app.
2. Paste a webpage URL into the **Page URL** field.
3. Click **Scan PDF Links**.
4. Select the PDFs you want using the checkboxes.
5. Choose a save folder.
6. Click **Download Checked**.
7. Review the status log in the app.
8. Check `download_log.csv` in the selected folder for download records.

## Building a Windows executable

Install PyInstaller:

```bash
pip install pyinstaller
```

Build a single-file Windows app:

```bash
pyinstaller --onefile --windowed --name "Mining Report PDF Downloader" app.py
```

The finished `.exe` will appear in:

```text
dist/Mining Report PDF Downloader.exe
```

## Disclaimer

This tool is intended for downloading publicly available documents only. Users are responsible for respecting website terms of service, robots.txt rules, copyright, rate limits, and applicable laws. Do not use this tool to bypass access controls or download restricted materials.

## Support

If this tool saves you time, consider supporting future development.

Donation/support link: `add your link here`
