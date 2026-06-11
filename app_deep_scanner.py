import sys
import csv
import time
import hashlib
import re
from collections import deque
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
from html.parser import HTMLParser

import requests

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QTextEdit,
    QMessageBox,
    QSpinBox,
)
from PyQt6.QtCore import Qt


USER_AGENT = "NI43101ResearchDownloader/1.1"
DEFAULT_DELAY_SECONDS = 3
TIMEOUT = 30


# -----------------------------
# HTML parser for PDF links and page links
# -----------------------------

class PDFLinkParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []
        self.page_links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            href = attrs.get("href")

            if href:
                self.current_href = urljoin(self.base_url, href)
                self.current_text = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current_href:
            full_url = normalize_url(self.current_href)
            link_text = " ".join(self.current_text).strip()

            if is_pdf_url(full_url):
                self.links.append(
                    {
                        "source_page": self.base_url,
                        "pdf_url": full_url,
                        "link_text": link_text,
                    }
                )
            elif is_probable_html_page(full_url):
                self.page_links.append(full_url)

            self.current_href = None
            self.current_text = []


# -----------------------------
# Helpers
# -----------------------------

def normalize_url(url):
    """Remove fragments like #section so the same page is not scanned repeatedly."""
    url, _fragment = urldefrag(url)
    return url.strip()


def is_pdf_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ["http", "https"] and parsed.path.lower().endswith(".pdf")


def is_probable_html_page(url):
    parsed = urlparse(url)

    if parsed.scheme not in ["http", "https"]:
        return False

    path = parsed.path.lower()

    # Avoid crawling obvious non-page assets.
    blocked_extensions = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".zip", ".rar", ".7z", ".mp4", ".mp3", ".css", ".js",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    )

    return not path.endswith(blocked_extensions)


def same_domain(url, starting_domain):
    return urlparse(url).netloc.lower() == starting_domain.lower()


def sanitize_filename(name):
    name = re.sub(r"[^\w\-. ]+", "_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._ ")

    if not name:
        name = "downloaded_report"

    if not name.lower().endswith(".pdf"):
        name += ".pdf"

    return name[:160]


def sha256_file(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def get_robots_parser(url):
    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return None, "Invalid URL"

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        response = requests.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )

        if response.status_code >= 400:
            return None, f"Could not read robots.txt: HTTP {response.status_code}"

        rp.parse(response.text.splitlines())
        return rp, "robots.txt checked"

    except Exception as e:
        return None, f"Could not read robots.txt: {e}"


def can_fetch(url):
    rp, note = get_robots_parser(url)

    if rp is None:
        return False, DEFAULT_DELAY_SECONDS, note

    allowed = rp.can_fetch(USER_AGENT, url)

    crawl_delay = rp.crawl_delay(USER_AGENT)
    if crawl_delay is None:
        crawl_delay = DEFAULT_DELAY_SECONDS

    return allowed, crawl_delay, note


def fetch_and_parse_page(page_url):
    allowed, delay, note = can_fetch(page_url)

    if not allowed:
        raise Exception(f"robots.txt blocks this page or could not be checked. Note: {note}")

    time.sleep(delay)

    response = requests.get(
        page_url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )

    if response.status_code in [403, 429]:
        raise Exception(
            f"Server returned HTTP {response.status_code}. Stop and do not hammer the site."
        )

    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type and content_type:
        # Some servers omit Content-Type. If it exists and is not HTML, skip parsing.
        return [], []

    parser = PDFLinkParser(page_url)
    parser.feed(response.text)

    return parser.links, parser.page_links


def find_pdf_links(page_url):
    pdf_links, _page_links = fetch_and_parse_page(page_url)

    unique = {}
    for item in pdf_links:
        unique[item["pdf_url"]] = item

    return list(unique.values())


def find_pdf_links_deep(start_url, max_depth=2, max_pages=50, log_callback=None, should_stop=None):
    """
    Limited same-domain crawler.

    Starts at start_url, scans that page for PDFs, then follows normal public links
    on the same domain up to max_depth clicks away.
    """
    start_url = normalize_url(start_url)
    starting_domain = urlparse(start_url).netloc

    if not starting_domain:
        raise Exception("Invalid starting URL")

    queue = deque([(start_url, 0)])
    visited_pages = set()
    unique_pdfs = {}
    scanned_count = 0

    while queue and scanned_count < max_pages:
        if should_stop and should_stop():
            if log_callback:
                log_callback("Deep scan stopped by user.")
            break

        page_url, depth = queue.popleft()
        page_url = normalize_url(page_url)

        if page_url in visited_pages:
            continue

        if not same_domain(page_url, starting_domain):
            continue

        visited_pages.add(page_url)
        scanned_count += 1

        if log_callback:
            log_callback(f"Deep scan page {scanned_count}/{max_pages}, depth {depth}: {page_url}")

        if should_stop and should_stop():
            if log_callback:
                log_callback("Deep scan stopped by user.")
            break

        try:
            pdf_links, page_links = fetch_and_parse_page(page_url)
        except Exception as e:
            if log_callback:
                log_callback(f"Skipped page: {page_url} ({e})")
            continue

        for item in pdf_links:
            unique_pdfs[item["pdf_url"]] = item

        if depth < max_depth:
            for link in page_links:
                if should_stop and should_stop():
                    if log_callback:
                        log_callback("Deep scan stopped by user.")
                    queue.clear()
                    break

                link = normalize_url(link)
                if link not in visited_pages and same_domain(link, starting_domain):
                    queue.append((link, depth + 1))

    if log_callback:
        log_callback(f"Deep scan completed. Scanned {scanned_count} page(s).")

    return list(unique_pdfs.values())


def write_log(folder, row):
    log_path = Path(folder) / "download_log.csv"
    exists = log_path.exists()

    fields = [
        "timestamp",
        "source_page",
        "pdf_url",
        "link_text",
        "local_filename",
        "local_path",
        "status_code",
        "content_type",
        "file_size_bytes",
        "sha256",
        "status",
        "notes",
    ]

    clean_row = {field: row.get(field, "") for field in fields}

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)

        if not exists:
            writer.writeheader()

        writer.writerow(clean_row)


def download_pdf(item, folder):
    pdf_url = item["pdf_url"]

    allowed, delay, note = can_fetch(pdf_url)

    if not allowed:
        write_log(
            folder,
            {
                "timestamp": datetime.now().isoformat(),
                "source_page": item["source_page"],
                "pdf_url": pdf_url,
                "link_text": item["link_text"],
                "status": "blocked_by_robots",
                "notes": note,
            },
        )

        return False, "Blocked by robots.txt"

    time.sleep(delay)

    parsed = urlparse(pdf_url)
    filename = sanitize_filename(Path(parsed.path).name)

    if filename.lower() == ".pdf":
        filename = sanitize_filename(item["link_text"])

    local_path = Path(folder) / filename

    if local_path.exists():
        digest = sha256_file(local_path)

        write_log(
            folder,
            {
                "timestamp": datetime.now().isoformat(),
                "source_page": item["source_page"],
                "pdf_url": pdf_url,
                "link_text": item["link_text"],
                "local_filename": filename,
                "local_path": str(local_path),
                "file_size_bytes": local_path.stat().st_size,
                "sha256": digest,
                "status": "skipped_existing",
                "notes": "File already exists",
            },
        )

        return True, "Skipped existing"

    try:
        response = requests.get(
            pdf_url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            stream=True,
        )

        status_code = response.status_code
        content_type = response.headers.get("Content-Type", "")

        if status_code in [403, 429]:
            raise Exception(f"Server returned HTTP {status_code}")

        response.raise_for_status()

        first_chunk = True
        total_bytes = 0

        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue

                if first_chunk:
                    first_chunk = False

                    if not chunk.startswith(b"%PDF"):
                        local_path.unlink(missing_ok=True)
                        raise Exception("Downloaded file does not appear to be a valid PDF")

                total_bytes += len(chunk)
                f.write(chunk)

        digest = sha256_file(local_path)

        write_log(
            folder,
            {
                "timestamp": datetime.now().isoformat(),
                "source_page": item["source_page"],
                "pdf_url": pdf_url,
                "link_text": item["link_text"],
                "local_filename": filename,
                "local_path": str(local_path),
                "status_code": status_code,
                "content_type": content_type,
                "file_size_bytes": total_bytes,
                "sha256": digest,
                "status": "downloaded",
                "notes": "OK",
            },
        )

        return True, f"Downloaded {filename}"

    except Exception as e:
        write_log(
            folder,
            {
                "timestamp": datetime.now().isoformat(),
                "source_page": item["source_page"],
                "pdf_url": pdf_url,
                "link_text": item["link_text"],
                "local_filename": filename,
                "local_path": str(local_path),
                "status": "failed",
                "notes": str(e),
            },
        )

        return False, str(e)


# -----------------------------
# GUI
# -----------------------------

class PDFDownloaderGUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PDF Downloader")
        self.resize(1000, 650)

        self.pdf_items = []
        self.stop_scan_requested = False
        self.destination_folder = str(Path.cwd() / "downloaded_pdfs")
        Path(self.destination_folder).mkdir(exist_ok=True)

        layout = QVBoxLayout()

        # URL row
        url_row = QHBoxLayout()
        url_label = QLabel("Page URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste webpage URL here")
        self.scan_button = QPushButton("Scan PDF Links")
        self.scan_button.clicked.connect(self.scan_links)
        self.deep_scan_button = QPushButton("Deep Scan PDF Links")
        self.deep_scan_button.clicked.connect(self.deep_scan_links)

        self.stop_scan_button = QPushButton("End Scan")
        self.stop_scan_button.clicked.connect(self.stop_deep_scan)
        self.stop_scan_button.setEnabled(False)

        url_row.addWidget(url_label)
        url_row.addWidget(self.url_input)
        url_row.addWidget(self.scan_button)
        url_row.addWidget(self.deep_scan_button)
        url_row.addWidget(self.stop_scan_button)
        layout.addLayout(url_row)

        # Deep scan settings row
        deep_row = QHBoxLayout()
        deep_row.addWidget(QLabel("Deep Scan Max Depth:"))
        self.max_depth_input = QSpinBox()
        self.max_depth_input.setRange(1, 3)
        self.max_depth_input.setValue(2)
        self.max_depth_input.setToolTip("Number of clicks away from the starting page. 1-2 is recommended.")
        deep_row.addWidget(self.max_depth_input)

        deep_row.addWidget(QLabel("Max Pages:"))
        self.max_pages_input = QSpinBox()
        self.max_pages_input.setRange(5, 200)
        self.max_pages_input.setValue(50)
        self.max_pages_input.setToolTip("Safety limit for pages scanned during deep scan.")
        deep_row.addWidget(self.max_pages_input)
        deep_row.addStretch()
        layout.addLayout(deep_row)

        # Folder row
        folder_row = QHBoxLayout()
        folder_label = QLabel("Save Folder:")
        self.folder_input = QLineEdit(self.destination_folder)
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_folder)

        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.folder_input)
        folder_row.addWidget(self.browse_button)
        layout.addLayout(folder_row)

        # PDF links list
        layout.addWidget(QLabel("PDF Links Found:"))

        self.link_list = QListWidget()
        self.link_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.link_list)

        # Buttons
        button_row = QHBoxLayout()

        self.check_all_button = QPushButton("Check All")
        self.check_all_button.clicked.connect(self.check_all_links)

        self.uncheck_all_button = QPushButton("Uncheck All")
        self.uncheck_all_button.clicked.connect(self.uncheck_all_links)

        self.download_checked_button = QPushButton("Download Checked")
        self.download_checked_button.clicked.connect(self.download_checked)

        self.clear_list_button = QPushButton("Clear Link List")
        self.clear_list_button.clicked.connect(self.clear_link_list)

        button_row.addWidget(self.check_all_button)
        button_row.addWidget(self.uncheck_all_button)
        button_row.addWidget(self.download_checked_button)
        button_row.addWidget(self.clear_list_button)
        layout.addLayout(button_row)

        # Log viewer
        layout.addWidget(QLabel("Status Log:"))

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        self.setLayout(layout)

    def log(self, message):
        self.log_output.append(message)
        QApplication.processEvents()

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Download Folder",
            self.folder_input.text(),
        )

        if folder:
            self.destination_folder = folder
            self.folder_input.setText(folder)

    def populate_pdf_list(self):
        self.link_list.clear()

        if not self.pdf_items:
            self.log("No PDF links found.")
            return

        for item in self.pdf_items:
            label = item["link_text"] or item["pdf_url"]

            list_item = QListWidgetItem(label)
            list_item.setToolTip(item["pdf_url"])
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Unchecked)

            self.link_list.addItem(list_item)

        self.log(f"Found {len(self.pdf_items)} PDF link(s).")

    def scan_links(self):
        page_url = self.url_input.text().strip()

        if not page_url:
            QMessageBox.warning(self, "Missing URL", "Please paste a webpage URL first.")
            return

        self.link_list.clear()
        self.pdf_items = []

        self.log(f"Scanning exact page only: {page_url}")

        try:
            self.pdf_items = find_pdf_links(page_url)
            self.populate_pdf_list()

        except Exception as e:
            self.log(f"Scan failed: {e}")
            QMessageBox.critical(self, "Scan Failed", str(e))

    def set_scanning_state(self, scanning):
        self.scan_button.setEnabled(not scanning)
        self.deep_scan_button.setEnabled(not scanning)
        self.stop_scan_button.setEnabled(scanning)
        self.max_depth_input.setEnabled(not scanning)
        self.max_pages_input.setEnabled(not scanning)

    def stop_deep_scan(self):
        self.stop_scan_requested = True
        self.log("Stop requested. Finishing current page, then ending scan...")

    def deep_scan_links(self):
        page_url = self.url_input.text().strip()

        if not page_url:
            QMessageBox.warning(self, "Missing URL", "Please paste a webpage URL first.")
            return

        self.link_list.clear()
        self.pdf_items = []

        max_depth = self.max_depth_input.value()
        max_pages = self.max_pages_input.value()

        self.stop_scan_requested = False
        self.set_scanning_state(True)

        self.log(f"Starting deep scan: {page_url}")
        self.log(f"Limits: same domain only, max depth {max_depth}, max pages {max_pages}")

        try:
            self.pdf_items = find_pdf_links_deep(
                page_url,
                max_depth=max_depth,
                max_pages=max_pages,
                log_callback=self.log,
                should_stop=lambda: self.stop_scan_requested,
            )
            self.populate_pdf_list()

        except Exception as e:
            self.log(f"Deep scan failed: {e}")
            QMessageBox.critical(self, "Deep Scan Failed", str(e))

        finally:
            self.set_scanning_state(False)
            self.stop_scan_requested = False

    def check_all_links(self):
        for i in range(self.link_list.count()):
            self.link_list.item(i).setCheckState(Qt.CheckState.Checked)

    def uncheck_all_links(self):
        for i in range(self.link_list.count()):
            self.link_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def clear_link_list(self):
        self.link_list.clear()
        self.pdf_items = []
        self.log("Cleared PDF link list.")

    def download_checked(self):
        folder = self.folder_input.text().strip()

        if not folder:
            QMessageBox.warning(self, "Missing Folder", "Please choose a destination folder.")
            return

        Path(folder).mkdir(parents=True, exist_ok=True)

        checked_indexes = []

        for i in range(self.link_list.count()):
            list_item = self.link_list.item(i)

            if list_item.checkState() == Qt.CheckState.Checked:
                checked_indexes.append(i)

        if not checked_indexes:
            QMessageBox.warning(self, "Nothing Checked", "Check one or more PDF links first.")
            return

        self.log(f"Downloading {len(checked_indexes)} checked PDF(s) to: {folder}")

        for index in checked_indexes:
            item = self.pdf_items[index]
            self.log(f"Downloading: {item['pdf_url']}")

            success, message = download_pdf(item, folder)

            if success:
                self.log(f"OK: {message}")
            else:
                self.log(f"FAILED: {message}")

        self.log("Done.")
        self.log(f"Download log saved to: {Path(folder) / 'download_log.csv'}")


def main():
    app = QApplication(sys.argv)
    window = PDFDownloaderGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
