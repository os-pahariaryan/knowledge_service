import argparse
import os
import sys
import uuid
import time
from pathlib import Path
from typing import List, Dict, Iterable, Optional

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from dotenv import load_dotenv

import chromadb
from chromadb.utils import embedding_functions


# ---------- Config & Chroma setup ----------

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("ERROR: OPENAI_API_KEY not set (did you run the .openai_config.json → .env script?).", file=sys.stderr)
    sys.exit(1)

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "kb_chunks")

DEFAULT_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "400"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))


def get_collection():
    """Get a persistent Chroma collection with OpenAI embedding function attached."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
    except Exception as e:
        print(f"FATAL: Could not create Chroma PersistentClient at {CHROMA_PATH}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        openai_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small",
        )
    except Exception as e:
        print(f"FATAL: Could not initialize OpenAIEmbeddingFunction: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=openai_ef,
        )
        return collection
    except Exception as e:
        print(f"FATAL: Could not get or create Chroma collection '{COLLECTION_NAME}': {e}", file=sys.stderr)
        sys.exit(1)


# ---------- Chunking (same style as server) ----------

def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """
    Chunk by paragraph first — better for docs.
    Falls back to word-based if paragraphs are too large.
    Mirrors your server logic so behavior is consistent.
    """
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_size = 0

    for para in paragraphs:
        words = para.split()
        para_size = len(words)

        if current_size + para_size > chunk_size:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            # Start new chunk with overlap
            overlap_words = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_words + words
            current_size = len(current_chunk)
        else:
            current_chunk.extend(words)
            current_size += para_size

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


# ---------- URL & sitemap loading ----------

def fetch_url(url: str, timeout: int = 20) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            print(f"WARNING: Got status {resp.status_code} for URL {url}", file=sys.stderr)
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"WARNING: Request failed for URL {url}: {e}", file=sys.stderr)
        return None


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join([ln for ln in lines if ln])
    return text


def parse_sitemap(sitemap_url: str, url_filter: str = None, max_pages: Optional[int] = None) -> List[str]:
    """Parse sitemap.xml and return filtered URLs, up to max_pages."""
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR: Failed to fetch sitemap {sitemap_url}: {e}", file=sys.stderr)
        sys.exit(1)

    soup = BeautifulSoup(response.text, "xml")
    urls = [loc.text for loc in soup.find_all("loc")]

    if url_filter:
        urls = [u for u in urls if url_filter in u]

    if max_pages is not None:
        urls = urls[:max_pages]

    if not urls:
        print(f"ERROR: No URLs found in sitemap after applying filter.", file=sys.stderr)
        sys.exit(1)

    return urls


# ---------- File loading ----------

def load_file_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"WARNING: Failed to read file {path}: {e}", file=sys.stderr)
        return None


def iter_files_under(path: str) -> Iterable[str]:
    for root, _, files in os.walk(path):
        for fname in files:
            if fname.startswith("."):
                continue
            yield os.path.join(root, fname)


# ---------- Chroma upsert with kb_id ----------

def delete_existing_doc_chunks(collection, kb_id: str, doc_id: str):
    """Optional: make ingest idempotent by removing old chunks for this kb_id+doc_id."""
    try:
        results = collection.get(
            where={"kb_id": kb_id, "doc_id": doc_id},
            ids=None,
            limit=None,
        )
        ids = results.get("ids") or []
        if not ids:
            return

        # Chroma may return nested lists; flatten if needed
        if isinstance(ids[0], list):
            flat_ids = [item for sub in ids for item in sub]
        else:
            flat_ids = ids

        if flat_ids:
            collection.delete(ids=flat_ids)
            print(f"INFO: Deleted {len(flat_ids)} existing chunks for kb_id={kb_id}, doc_id={doc_id}")
    except Exception as e:
        print(f"WARNING: Failed to delete existing chunks for kb_id={kb_id}, doc_id={doc_id}: {e}", file=sys.stderr)


def upsert_chunks_chroma(
    collection,
    kb_id: str,
    doc_id: str,
    chunks: List[str],
    source: str,
    extra_metadata: Optional[Dict] = None,
):
    """Add document chunks to Chroma; embedding handled by collection's OpenAIEmbeddingFunction."""
    if not chunks:
        print(f"INFO: No chunks to ingest for doc_id={doc_id}")
        return

    # Idempotent behavior
    delete_existing_doc_chunks(collection, kb_id, doc_id)

    ids: List[str] = []
    metadatas: List[Dict] = []

    for idx, _ in enumerate(chunks):
        ids.append(str(uuid.uuid4()))
        md = {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "source": source,
            "chunk_index": idx,
        }
        if extra_metadata:
            md.update(extra_metadata)
        metadatas.append(md)

    try:
        collection.add(
            ids=ids,
            documents=chunks,
            metadatas=metadatas,
        )
        print(f"INFO: Ingested {len(chunks)} chunks for kb_id={kb_id}, doc_id={doc_id}")
    except Exception as e:
        print(f"ERROR: Failed to add chunks to Chroma for kb_id={kb_id}, doc_id={doc_id}: {e}", file=sys.stderr)


# ---------- Ingest flows ----------

def ingest_sitemap_to_kb(
    kb_id: str,
    sitemap_url: str,
    url_filter: Optional[str],
    max_pages: int,
    chunk_size: int,
    chunk_overlap: int,
):
    urls = parse_sitemap(sitemap_url, url_filter=url_filter, max_pages=max_pages)
    collection = get_collection()

    total_chunks = 0
    pages_done = 0
    failed = 0

    for url in tqdm(urls, desc=f"Ingesting sitemap URLs into kb_id={kb_id}"):
        html = fetch_url(url)
        if not html:
            failed += 1
            continue
        text = html_to_text(html)
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            print(f"WARNING: No chunks extracted for URL {url}", file=sys.stderr)
            failed += 1
            continue

        doc_id = url  # stable ID
        extra_md = {"source_type": "url"}
        upsert_chunks_chroma(collection, kb_id, doc_id, chunks, source=url, extra_metadata=extra_md)
        total_chunks += len(chunks)
        pages_done += 1

    print(
        f"INFO: Sitemap ingest finished. kb_id={kb_id}, "
        f"pages_crawled={pages_done}, pages_failed={failed}, total_chunks={total_chunks}"
    )


def ingest_url_list_to_kb(
    kb_id: str,
    url_list_path: str,
    chunk_size: int,
    chunk_overlap: int,
):
    url_file = Path(url_list_path)
    if not url_file.exists():
        print(f"ERROR: URL list file not found: {url_list_path}", file=sys.stderr)
        sys.exit(1)

    urls = [
        line.strip()
        for line in url_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        print("ERROR: No URLs found in list file.", file=sys.stderr)
        sys.exit(1)

    collection = get_collection()

    total_chunks = 0
    pages_done = 0
    failed = 0

    for url in tqdm(urls, desc=f"Ingesting URL list into kb_id={kb_id}"):
        html = fetch_url(url)
        if not html:
            failed += 1
            continue
        text = html_to_text(html)
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            print(f"WARNING: No chunks extracted for URL {url}", file=sys.stderr)
            failed += 1
            continue

        doc_id = url
        extra_md = {"source_type": "url"}
        upsert_chunks_chroma(collection, kb_id, doc_id, chunks, source=url, extra_metadata=extra_md)
        total_chunks += len(chunks)
        pages_done += 1

    print(
        f"INFO: URL list ingest finished. kb_id={kb_id}, "
        f"pages_crawled={pages_done}, pages_failed={failed}, total_chunks={total_chunks}"
    )


def ingest_files_to_kb(
    kb_id: str,
    root_path: str,
    chunk_size: int,
    chunk_overlap: int,
):
    root = Path(root_path)
    if not root.exists():
        print(f"ERROR: Path not found: {root_path}", file=sys.stderr)
        sys.exit(1)

    files = list(iter_files_under(str(root)))
    if not files:
        print(f"ERROR: No files found under {root_path}", file=sys.stderr)
        sys.exit(1)

    collection = get_collection()

    total_chunks = 0
    files_done = 0
    failed = 0

    for path in tqdm(files, desc=f"Ingesting files into kb_id={kb_id}"):
        text = load_file_text(path)
        if not text:
            failed += 1
            continue
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            print(f"WARNING: No chunks for file {path}", file=sys.stderr)
            failed += 1
            continue

        doc_id = os.path.relpath(path, str(root))
        extra_md = {"source_type": "file"}
        upsert_chunks_chroma(collection, kb_id, doc_id, chunks, source=path, extra_metadata=extra_md)
        total_chunks += len(chunks)
        files_done += 1

    print(
        f"INFO: File ingest finished. kb_id={kb_id}, "
        f"files_ingested={files_done}, files_failed={failed}, total_chunks={total_chunks}"
    )


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(
        description="Offline Chroma ingester: build a kb_id by ingesting sitemap, URL list, or files."
    )
    parser.add_argument(
        "--kb_id",
        required=True,
        help="Logical knowledge base ID (e.g. 'stripe_docs').",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sitemap mode
    sitemap_p = subparsers.add_parser("sitemap", help="Ingest from a sitemap.xml URL")
    sitemap_p.add_argument("--sitemap_url", required=True, help="Sitemap URL (e.g. https://stripe.com/sitemap.xml)")
    sitemap_p.add_argument("--url_filter", default=None, help="Filter URLs containing this substring (e.g. /docs)")
    sitemap_p.add_argument("--max_pages", type=int, default=50, help="Max pages to ingest from sitemap")

    # URL list mode
    url_list_p = subparsers.add_parser("urllist", help="Ingest from a text file with one URL per line")
    url_list_p.add_argument("--url_list", required=True, help="Path to file containing URLs")

    # Files mode
    files_p = subparsers.add_parser("files", help="Ingest files under a directory")
    files_p.add_argument("--path", required=True, help="Root directory of documents")

    # Shared chunking options
    for sp in (sitemap_p, url_list_p, files_p):
        sp.add_argument("--chunk_size", type=int, default=DEFAULT_CHUNK_SIZE)
        sp.add_argument("--chunk_overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)

    args = parser.parse_args()

    start = time.time()
    try:
        if args.command == "sitemap":
            ingest_sitemap_to_kb(
                kb_id=args.kb_id,
                sitemap_url=args.sitemap_url,
                url_filter=args.url_filter,
                max_pages=args.max_pages,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        elif args.command == "urllist":
            ingest_url_list_to_kb(
                kb_id=args.kb_id,
                url_list_path=args.url_list,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        elif args.command == "files":
            ingest_files_to_kb(
                kb_id=args.kb_id,
                root_path=args.path,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        else:
            print("ERROR: Unknown command.", file=sys.stderr)
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nINFO: Ingestion interrupted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL: Unhandled exception in ingestion: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        elapsed = time.time() - start
        print(f"INFO: Ingestion run finished in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
