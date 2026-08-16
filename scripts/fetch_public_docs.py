#!/usr/bin/env python3
"""Fetch public documents into the UEAF RAG test corpus (Phase 1).

Only public / openly-licensed sources are used; every document records
provenance (original URL, license, fetched_at, source_version) in
document/sources.json, so the corpus stays auditable (enterprise RAG needs
traceable evidence).

Phase 1 sources (stable, no-auth or generous public APIs):
  - arXiv (open access)                    -> 02-tech-api
  - RFC Editor (public domain)             -> 02-tech-api
  - GitHub OSS repos (Apache-2.0): README  -> 01-product
  - GitHub OSS repos: CHANGELOG/HISTORY    -> 06-project-delivery
  - GitHub OSS repos: CONTRIBUTING/CoC     -> 03-policy-sop
  - StackExchange Q&A (CC BY-SA)           -> 05-faq-support
  - Apache Foundation minutes (public)     -> 08-meeting-decision
  - Wikipedia revisions (CC BY-SA)         -> 09-version-conflict
  - Wikipedia random pages (CC BY-SA)      -> 10-noise

Categories with no reliable public Phase-1 source (04-sales-pre, 07-training-hr)
are skipped and reported; they are deferred to Phase 2.

Usage:
  # ratio-based batch (default total budget 1000, ~830 docs across 8 categories)
  python3 scripts/fetch_public_docs.py
  # fetch exactly one category
  python3 scripts/fetch_public_docs.py --category 10-noise --limit 12
  # print plan without network
  python3 scripts/fetch_public_docs.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "document" / "manifest.json"
SOURCES_JSON = ROOT / "document" / "sources.json"
DEFAULT_RAW = ROOT / "document" / "raw"

UA = "ueaf-corpus-fetch/0.1 (local test corpus; contact: internal)"

# category_id -> short filename prefix (matches manifest source_ref_prefix tails)
PREFIX = {
    "01-product": "product",
    "02-tech-api": "tech",
    "03-policy-sop": "policy",
    "04-sales-pre": "sales",
    "05-faq-support": "faq",
    "06-project-delivery": "project",
    "07-training-hr": "training",
    "08-meeting-decision": "meeting",
    "09-version-conflict": "version",
    "10-noise": "noise",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("fetch")

# Global content cap for text files; None = store full content. Set via --max-chars.
MAX_CHARS: int | None = 4000


def cut(text: str) -> str:
    """Apply the configured content cap (None/0 = keep full content)."""
    return text[:MAX_CHARS] if MAX_CHARS else text


def http_get(url: str, *, timeout: int = 30, retries: int = 3) -> bytes:
    """GET with retry + exponential backoff.

    Permanent HTTP errors (404/410) are not retried; transient failures
    (timeouts, 5xx) are retried with backoff.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise  # permanent: do not waste retries
            last = exc
        except Exception as exc:  # noqa: BLE001 - network is best-effort
            last = exc
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")


# ---------------------------------------------------------------- arXiv
def fetch_arxiv(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    """Recent cs.AI/cs.SE/cs.LG abstracts (open access)."""
    q = urllib.parse.quote("cat:cs.AI OR cat:cs.SE OR cat:cs.LG")
    url = (
        f"http://export.arxiv.org/api/query?search_query={q}"
        f"&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    )
    root = ET.fromstring(http_get(url))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out: list[tuple] = []
    for i, entry in enumerate(root.findall("a:entry", ns)):
        title = (entry.findtext("a:title", "", ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("a:summary", "", ns) or "").strip()
        link_el = entry.find("a:id", ns)
        link = link_el.text if link_el is not None else url
        text = f"# {title}\n\n{summary}\n\nSource: {link}\n"
        out.append((f"arxiv-{i + 1:04d}", "txt", text, "open-access", link))
        time.sleep(delay)
    return out


def fetch_arxiv_pdf(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    """Real PDF files of recent arXiv papers (open access, zero deps)."""
    q = urllib.parse.quote("cat:cs.AI OR cat:cs.SE OR cat:cs.LG")
    url = (
        f"http://export.arxiv.org/api/query?search_query={q}"
        f"&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    )
    root = ET.fromstring(http_get(url))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out: list[tuple] = []
    for i, entry in enumerate(root.findall("a:entry", ns)):
        pdf_url = None
        for link in entry.findall("a:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
                break
        if not pdf_url:
            continue
        try:
            data = http_get(pdf_url, timeout=90)
        except Exception as exc:  # noqa: BLE001
            log.warning("arxiv pdf %s skip: %s", pdf_url, exc)
            continue
        if data[:4] != b"%PDF":
            log.warning("arxiv pdf %s skip: not a PDF", pdf_url)
            continue
        out.append((f"arxiv-{i + 1:04d}", "pdf", data, "open-access", pdf_url))
        time.sleep(delay)
    return out


# ---------------------------------------------------------------- RFC
def fetch_rfc(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    """Plain-text RFCs (public domain). Fixed seed -> reproducible pick."""
    idx = http_get("https://www.rfc-editor.org/rfc-index.txt").decode("utf-8", "replace")
    nums = sorted({int(m) for m in re.findall(r"RFC\s*(\d{4,5})", idx, re.I) if int(m) >= 1})
    random.Random(20260816).shuffle(nums)  # deterministic sample
    out: list[tuple] = []
    for n in nums[:limit]:
        url = f"https://www.rfc-editor.org/rfc/rfc{n}.txt"
        try:
            body = http_get(url).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            log.warning("rfc %s skip: %s", n, exc)
            continue
        out.append(
            (f"rfc{n}", "txt", cut(body), "public-domain", f"https://www.rfc-editor.org/rfc/rfc{n}.html")
        )
        time.sleep(delay)
    return out


# ---------------------------------------------------------------- GitHub (Apache-2.0 OSS)
def _github_repos(limit: int, *, license_q: str, stars_q: str) -> list[tuple[str, str | None]]:
    url = (
        "https://api.github.com/search/repositories?q="
        + urllib.parse.quote(f"license:{license_q} stars:{stars_q}")
        + f"&sort=stars&order=desc&per_page={min(limit, 100)}"
    )
    data = json.loads(http_get(url, timeout=30))
    items = []
    for it in data.get("items", []):
        lic = (it.get("license") or {}).get("spdx_id")
        items.append((it["full_name"], lic))
    return items


def _github_fetch(limit: int, files: tuple[str, ...], *, delay: float) -> list[tuple]:
    """Fetch one of `files` from openly-licensed (Apache-2.0) OSS repos."""
    out: list[tuple] = []
    for full, lic in _github_repos(limit, license_q="apache-2.0", stars_q=">500"):
        if len(out) >= limit:
            break
        owner, repo = full.split("/")
        for fname in files:
            raw = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{fname}"
            try:
                body = http_get(raw, timeout=20).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - file may not exist
                continue
            if len(body.strip()) < 200:
                continue  # placeholder / empty
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{owner}-{repo}")
            out.append(
                (name, "md", cut(body), lic or "apache-2.0", f"https://github.com/{full}/blob/HEAD/{fname}")
            )
            break  # one doc per repo
        time.sleep(delay)
    return out


def fetch_github_readme(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    return _github_fetch(limit, ("README.md", "README.rst", "README.adoc", "readme.md", "README.txt"), delay=delay)


def fetch_github_changelog(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    return _github_fetch(limit, ("CHANGELOG.md", "CHANGES.md", "HISTORY.md"), delay=delay)


def fetch_github_policy(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    return _github_fetch(limit, ("CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"), delay=delay)


# ---------------------------------------------------------------- StackExchange Q&A
def fetch_stackexchange_qa(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    """Recent StackOverflow questions+body as FAQ-like docs (CC BY-SA)."""
    url = (
        "https://api.stackexchange.com/2.3/questions?site=stackoverflow&filter=withbody"
        f"&pagesize={min(limit, 100)}&order=desc&sort=activity"
    )
    data = json.loads(http_get(url, timeout=30))
    out: list[tuple] = []
    for i, q in enumerate(data.get("items", [])):
        title = q.get("title", "")
        body = re.sub(r"<[^>]+>", " ", q.get("body", "")).strip()
        text = f"# {title}\n\nQ: {body}\n\nSource: {q.get('link')}\n"
        out.append((f"so-{q.get('question_id', i + 1)}", "txt", cut(text), "CC-BY-SA", q.get("link", url)))
        time.sleep(delay)
    return out


# ---------------------------------------------------------------- Apache minutes
def fetch_apache_minutes(_cat: str, limit: int, *, delay: float) -> list[tuple]:
    """Apache Foundation public meeting minutes (public)."""
    idx_url = "https://www.apache.org/foundation/records/minutes/"
    idx = http_get(idx_url).decode("utf-8", "replace")
    links: list[str] = []
    for href in re.findall(r'href="([^"]+\.html)"', idx, re.I):
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            links.append("https://www.apache.org" + href)
        else:
            links.append(urllib.parse.urljoin(idx_url, href))
    uniq = list(dict.fromkeys(links))[:limit]
    out: list[tuple] = []
    for i, u in enumerate(uniq):
        try:
            body = http_get(u, timeout=20).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            log.warning("minutes %s skip: %s", u, exc)
            continue
        out.append((f"minutes-{i + 1:04d}", "html", cut(body), "apache-2.0", u))
        time.sleep(delay)
    return out


# ---------------------------------------------------------------- Wikipedia
def _wiki_random_titles(n: int, lang: str = "en") -> list[str]:
    url = (
        f"https://{lang}.wikipedia.org/w/api.php?action=query&list=random"
        f"&rnnamespace=0&rnlimit={n}&format=json"
    )
    data = json.loads(http_get(url))
    return [p["title"] for p in data.get("query", {}).get("random", [])]


def _wiki_page_text(title: str, lang: str = "en") -> str:
    t = urllib.parse.quote(title)
    url = (
        f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts"
        f"&explaintext=1&titles={t}&format=json"
    )
    data = json.loads(http_get(url))
    for page in data.get("query", {}).get("pages", {}).values():
        return page.get("extract", "") or ""
    return ""


def _wiki_revision_text(title: str, revid: int, lang: str = "en") -> str:
    url = (
        f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=revisions"
        f"&rvprop=content&rvslots=main&revids={revid}&format=json"
    )
    data = json.loads(http_get(url))
    for page in data.get("query", {}).get("pages", {}).values():
        revs = page.get("revisions", [])
        if revs:
            return revs[0].get("slots", {}).get("main", {}).get("*", "")
    return ""


def fetch_wikipedia_random(_cat: str, limit: int, *, delay: float, lang: str = "en") -> list[tuple]:
    """Random pages -> noise / irrelevant corpus (CC BY-SA)."""
    out: list[tuple] = []
    for i, title in enumerate(_wiki_random_titles(limit, lang)):
        text = _wiki_page_text(title, lang)
        if not text:
            continue
        out.append((f"wiki-{i + 1:04d}", "txt", cut(text), "CC-BY-SA", f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}"))
        time.sleep(delay)
    return out


def fetch_wikipedia_revisions(_cat: str, limit: int, *, delay: float, lang: str = "en") -> list[tuple]:
    """Old+new revision pair of random pages -> version/conflict corpus."""
    out: list[tuple] = []
    for i, title in enumerate(_wiki_random_titles(limit, lang)):
        t = urllib.parse.quote(title)
        meta_url = (
            f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=revisions"
            f"&rvprop=ids&rvlimit=2&rvdir=newer&titles={t}&format=json"
        )
        data = json.loads(http_get(meta_url))
        page = next(iter(data.get("query", {}).get("pages", {}).values()), {})
        revs = page.get("revisions", [])
        if len(revs) < 2:
            continue
        rid_old, rid_new = revs[0]["revid"], revs[-1]["revid"]
        old_text = _wiki_revision_text(title, rid_old, lang)
        new_text = _wiki_revision_text(title, rid_new, lang)
        base = f"wiki-{i + 1:04d}"
        out.append((f"{base}-v1", "txt", cut(old_text), "CC-BY-SA", f"https://{lang}.wikipedia.org/?oldid={rid_old}"))
        out.append((f"{base}-v2", "txt", cut(new_text), "CC-BY-SA", f"https://{lang}.wikipedia.org/?oldid={rid_new}"))
        time.sleep(delay)
    return out


# category_id -> list of (fetcher, fraction_of_category_budget)
SOURCES: dict[str, list[tuple[object, float]]] = {
    "01-product": [(fetch_github_readme, 1.0)],
    "02-tech-api": [(fetch_arxiv, 0.5), (fetch_rfc, 0.5)],
    "03-policy-sop": [(fetch_github_policy, 1.0)],
    "05-faq-support": [(fetch_stackexchange_qa, 1.0)],
    "06-project-delivery": [(fetch_github_changelog, 1.0)],
    "08-meeting-decision": [(fetch_apache_minutes, 1.0)],
    "09-version-conflict": [(fetch_wikipedia_revisions, 1.0)],
    "10-noise": [(fetch_wikipedia_random, 1.0)],
}
# Not covered by a public Phase-1 source (deferred to Phase 2):
SKIPPED_PHASE1 = ["04-sales-pre", "07-training-hr"]


def _load_sources() -> list[dict]:
    if SOURCES_JSON.exists():
        try:
            data = json.loads(SOURCES_JSON.read_text())
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _save_sources(prov: list[dict]) -> None:
    SOURCES_JSON.write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch public docs into the RAG test corpus (Phase 1)")
    ap.add_argument("--limit", type=int, default=1000, help="total batch budget (default 1000)")
    ap.add_argument("--category", help="fetch only this category_id (then --limit is that category's target)")
    ap.add_argument("--delay", type=float, default=0.6, help="seconds between requests per source")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without network")
    ap.add_argument("--pdf", action="store_true", help="use real arXiv PDFs instead of text abstracts (02-tech-api)")
    ap.add_argument("--max-chars", type=int, default=4000, help="max chars per text file, 0 = store full content")
    ap.add_argument("--raw", default=str(DEFAULT_RAW), help="raw corpus root")
    args = ap.parse_args()

    global MAX_CHARS
    MAX_CHARS = None if args.max_chars <= 0 else args.max_chars

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cats = {c["category_id"]: c for c in manifest["distribution"]}
    raw = Path(args.raw)
    provenance = _load_sources()
    now = datetime.now(timezone.utc).isoformat()
    written = 0

    targets = [args.category] if args.category else list(SOURCES)
    for cat in targets:
        if cat not in SOURCES:
            log.info("skip %s: no public Phase-1 source", cat)
            continue
        if args.category:
            budget = args.limit
        else:
            budget = max(1, round(args.limit * cats[cat]["ratio"]))
        prefix = PREFIX[cat]
        outdir = raw / cat
        outdir.mkdir(parents=True, exist_ok=True)
        existing = sorted(outdir.glob(f"{prefix}-*"))
        seq = len(existing)
        if args.dry_run:
            parts: list[str] = []
            for func, frac in SOURCES[cat]:
                if args.pdf and func is fetch_arxiv:
                    func = fetch_arxiv_pdf
                parts.append(f"{getattr(func, '__name__', func)}x{max(1, round(budget * frac))}")
            log.info("[%s] dry-run plan (budget=%d): %s", cat, budget, " + ".join(parts))
            continue
        for func, frac in SOURCES[cat]:
            if args.pdf and func is fetch_arxiv:
                func = fetch_arxiv_pdf
            n = max(1, int(round(budget * frac)))
            log.info("[%s] fetching %d from %s", cat, n, getattr(func, "__name__", func))
            items = func(cat, n, delay=args.delay)
            for name, ext, content, lic, url in items:
                seq += 1
                fname = f"{prefix}-{seq:04d}.{ext}"
                source_ref = f"{cats[cat]['source_ref_prefix']}:{seq:04d}"
                if isinstance(content, bytes):
                    (outdir / fname).write_bytes(content)
                else:
                    (outdir / fname).write_text(content, encoding="utf-8")
                provenance.append(
                    {
                        "source_ref": source_ref,
                        "file": f"raw/{cat}/{fname}",
                        "original_url": url,
                        "license": lic,
                        "fetched_at": now,
                        "source_version": "1.0.0",
                        "category": cat,
                        "format": ext,
                    }
                )
                written += 1
        log.info("[%s] done, category now has %d files", cat, len(sorted(outdir.glob(f"{prefix}-*"))))

    if not args.dry_run:
        _save_sources(provenance)
        log.info("saved provenance -> %s (%d records)", SOURCES_JSON, len(provenance))
    log.info("Phase 1 written=%d. Skipped in Phase 1: %s", written, ", ".join(SKIPPED_PHASE1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
