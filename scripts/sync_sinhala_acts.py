#!/usr/bin/env python3
"""
Direct scraper/updater for Sri Lanka Acts (Sinhala only).

It scrapes the government acts listing pages, discovers Sinhala PDF links,
upserts `doc.json` metadata, and downloads missing `doc.pdf` files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

START_YEAR = 1981
ACTS_INDEX_URL = "https://documents.gov.lk/view/act/acts.html"
DECADE_RE = re.compile(r"^\d{4}s$")
YEAR_RE = re.compile(r"^\d{4}$")
PDF_RE = re.compile(r'href=["\']([^"\']+?_S\.pdf)["\']', re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
ROW_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
DOC_NUMBER_RE = re.compile(r"^(\d+)/(\d{4})$")
NUMBER_RE = re.compile(r"(\d+)-(\d{4})_S\.pdf$", re.IGNORECASE)
USER_AGENT = "Mozilla/5.0 (compatible; SriLankaActsBot/1.0)"


@dataclass
class Stats:
    count: int = 0
    min_date: str | None = None
    max_date: str | None = None
    scraped: int = 0
    metadata_updated: int = 0
    pdfs_downloaded: int = 0
    pdfs_skipped: int = 0
    pdf_failures: list[str] = field(default_factory=list)

    def track_date(self, date_str: str | None) -> None:
        if not date_str:
            return
        if self.min_date is None or date_str < self.min_date:
            self.min_date = date_str
        if self.max_date is None or date_str > self.max_date:
            self.max_date = date_str


def clean_text(html_fragment: str) -> str:
    text = TAG_RE.sub(" ", html_fragment)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def format_doc_number(raw: str) -> str | None:
    match = DOC_NUMBER_RE.match(raw.strip())
    if not match:
        return None
    return f"{int(match.group(1)):02d}/{match.group(2)}"


def make_doc_id(date_str: str, act_number: int, year: int) -> str:
    act_token = f"{act_number:02d}"
    return f"{date_str}-{date_str}-{act_token}-{year}-si"


def make_num(date_str: str, act_number: int, year: int) -> str:
    return f"{date_str}-{act_number:02d}-{year}-si"


def get_year_page(session: requests.Session, year: int) -> tuple[str | None, str | None]:
    candidates = [
        f"https://documents.gov.lk/view/act/acts_{year}.html",
        f"https://www.documents.gov.lk/view/act/acts_{year}.html",
        # Legacy paths kept as fallback.
        f"https://documents.gov.lk/view/acts/acts_{year}.html",
        f"https://www.documents.gov.lk/view/acts/acts_{year}.html",
    ]
    for url in candidates:
        try:
            response = session.get(url, timeout=40)
            if response.status_code == 200 and "_S.pdf" in response.text:
                return response.text, url
        except requests.RequestException:
            continue
    return None, None


def parse_table_row(row_html: str, page_url: str, year: int) -> dict | None:
    cells = TD_RE.findall(row_html)
    if len(cells) < 4:
        return None

    doc_number = format_doc_number(clean_text(cells[0]))
    if not doc_number:
        return None

    date_str = clean_text(cells[1])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        date_str = f"{year}-01-01"

    description = clean_text(cells[2])
    links = PDF_RE.findall(cells[3])
    if not links:
        return None

    pdf_url = urljoin(page_url, links[0])
    file_name = pdf_url.rstrip("/").split("/")[-1]
    number_match = NUMBER_RE.search(file_name)
    act_number = int(number_match.group(1)) if number_match else int(doc_number.split("/")[0])

    return {
        "doc_type": "lk_acts",
        "doc_id": make_doc_id(date_str, act_number, year),
        "num": make_num(date_str, act_number, year),
        "date_str": date_str,
        "description": description,
        "url_metadata": page_url,
        "lang": "si",
        "url_pdf": pdf_url,
        "doc_number": doc_number,
    }


def extract_year_docs(session: requests.Session, year: int) -> list[dict]:
    html, page_url = get_year_page(session, year)
    if not html or not page_url:
        return []

    docs: list[dict] = []
    seen_doc_numbers: set[str] = set()
    for row in ROW_RE.findall(html):
        doc = parse_table_row(row, page_url, year)
        if not doc:
            continue
        if doc["doc_number"] in seen_doc_numbers:
            continue
        seen_doc_numbers.add(doc["doc_number"])
        docs.append(doc)
    return docs


def remove_noisy_files(repo_root: Path) -> None:
    for file_name in [
        "docs_all.tsv",
        "docs_last100.tsv",
        "docs_last1000.tsv",
        "docs_last10000.tsv",
        "docs_by_decade_and_lang.png",
    ]:
        target = repo_root / file_name
        if target.exists():
            target.unlink()

    for readme in repo_root.glob("**/README.md"):
        if readme.parent == repo_root:
            continue
        readme.unlink(missing_ok=True)


def index_existing_docs(repo_root: Path) -> dict[str, tuple[Path, dict]]:
    by_doc_number: dict[str, tuple[Path, dict]] = {}
    for decade in repo_root.iterdir():
        if not decade.is_dir() or not DECADE_RE.match(decade.name):
            continue
        for year_dir in decade.iterdir():
            if not year_dir.is_dir() or not YEAR_RE.match(year_dir.name):
                continue
            for doc_dir in year_dir.iterdir():
                doc_json = doc_dir / "doc.json"
                if not doc_json.exists():
                    continue
                try:
                    data = json.loads(doc_json.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                doc_number = data.get("doc_number")
                if doc_number:
                    by_doc_number[format_doc_number(doc_number) or doc_number] = (doc_dir, data)
    return by_doc_number


def ensure_doc(repo_root: Path, doc: dict, existing: dict[str, tuple[Path, dict]]) -> Path:
    doc_number = doc["doc_number"]
    if doc_number in existing:
        doc_dir, current = existing[doc_number]
        doc["doc_id"] = current["doc_id"]
        doc["num"] = current.get("num", doc["num"])
    else:
        year = int(doc["date_str"][:4])
        decade = f"{year // 10 * 10}s"
        doc_dir = repo_root / decade / str(year) / doc["doc_id"]
        doc_dir.mkdir(parents=True, exist_ok=True)
        existing[doc_number] = (doc_dir, doc)

    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "doc.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    existing[doc_number] = (doc_dir, doc)
    return doc_dir


def should_download_pdf(pdf_path: Path) -> bool:
    return not pdf_path.exists() or pdf_path.stat().st_size == 0


def download_pdf(session: requests.Session, doc: dict, doc_dir: Path, stats: Stats) -> None:
    pdf_path = doc_dir / "doc.pdf"
    if not should_download_pdf(pdf_path):
        stats.pdfs_skipped += 1
        return

    try:
        response = session.get(doc["url_pdf"], timeout=120)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise ValueError("response is not a PDF")
        pdf_path.write_bytes(response.content)
        stats.pdfs_downloaded += 1
    except (requests.RequestException, ValueError) as exc:
        stats.pdf_failures.append(f"{doc['doc_number']}: {exc}")


def scan_existing(repo_root: Path) -> Stats:
    stats = Stats()
    for decade in repo_root.iterdir():
        if not decade.is_dir() or not DECADE_RE.match(decade.name):
            continue
        for year_dir in decade.iterdir():
            if not year_dir.is_dir() or not YEAR_RE.match(year_dir.name):
                continue
            for doc_dir in year_dir.iterdir():
                doc_json = doc_dir / "doc.json"
                if not doc_json.exists():
                    continue
                stats.count += 1
                try:
                    data = json.loads(doc_json.read_text(encoding="utf-8"))
                    stats.track_date(data.get("date_str"))
                except json.JSONDecodeError:
                    continue
    return stats


def verify_against_gov(session: requests.Session, existing: dict[str, tuple[Path, dict]]) -> tuple[list[str], list[str]]:
    current_year = datetime.now(timezone.utc).year
    gov_docs: dict[str, dict] = {}
    for year in range(START_YEAR, current_year + 1):
        for doc in extract_year_docs(session, year):
            gov_docs[doc["doc_number"]] = doc

    local_numbers = set(existing)
    gov_numbers = set(gov_docs)
    missing = sorted(gov_numbers - local_numbers, key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0])))
    extra = sorted(local_numbers - gov_numbers, key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0])))
    return missing, extra


def write_summary(repo_root: Path, stats: Stats) -> None:
    summary = {
        "dataset": "Sri Lanka Acts (Sinhala only)",
        "source": "https://documents.gov.lk",
        "source_note": "Scraped directly from official acts listing pages",
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "n_docs": stats.count,
        "date_str_min": stats.min_date,
        "date_str_max": stats.max_date,
        "langs": ["si"],
    }
    (repo_root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    repo_root = Path.cwd()
    remove_noisy_files(repo_root)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    existing = index_existing_docs(repo_root)
    run_stats = Stats()

    current_year = datetime.now(timezone.utc).year
    for year in range(START_YEAR, current_year + 1):
        year_docs = extract_year_docs(session, year)
        run_stats.scraped += len(year_docs)
        for doc in year_docs:
            doc_dir = ensure_doc(repo_root, doc, existing)
            run_stats.metadata_updated += 1
            download_pdf(session, doc, doc_dir, run_stats)

    stats = scan_existing(repo_root)
    write_summary(repo_root, stats)

    missing, extra = verify_against_gov(session, existing)
    print(f"Scraped {run_stats.scraped} acts from {ACTS_INDEX_URL}")
    print(f"Dataset ready: {stats.count} docs ({stats.min_date}..{stats.max_date})")
    print(f"Metadata updated: {run_stats.metadata_updated}")
    print(f"PDFs downloaded: {run_stats.pdfs_downloaded}, skipped: {run_stats.pdfs_skipped}")
    if run_stats.pdf_failures:
        print(f"PDF download failures ({len(run_stats.pdf_failures)}):")
        for failure in run_stats.pdf_failures:
            print(f"  - {failure}")
    if missing:
        print(f"Still missing from repo ({len(missing)}):")
        for doc_number in missing:
            print(f"  - {doc_number}")
    if extra:
        print(f"Extra in repo not on gov.lk ({len(extra)}):")
        for doc_number in extra:
            print(f"  - {doc_number}")
    if not missing and not extra and not run_stats.pdf_failures:
        print("Verification passed: repo matches gov.lk Sinhala acts.")


if __name__ == "__main__":
    main()
