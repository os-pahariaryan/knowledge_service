
# knowledge_service_poc_clean.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import chromadb
from openai import OpenAI, OpenAIError, RateLimitError
import asyncio
import uuid
import os
from dotenv import load_dotenv
from crawl4ai import AsyncWebCrawler
from crawl4ai.extraction_strategy import NoExtractionStrategy

load_dotenv()

app = FastAPI(title="Knowledge Service POC")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

chroma_client = chromadb.Client()
collection = chroma_client.create_collection("knowledge_poc")

# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class IngestURLRequest(BaseModel):
    url: str
    kb_id: Optional[str] = "default"
    deep_crawl: Optional[bool] = False    # crawl linked pages too
    max_pages: Optional[int] = 20         # limit for deep crawl

class IngestSitemapRequest(BaseModel):
    sitemap_url: str                       # e.g. https://stripe.com/sitemap.xml
    kb_id: Optional[str] = "default"
    max_pages: Optional[int] = 50
    url_filter: Optional[str] = None      # e.g. "/docs" to only crawl doc pages

class IngestTextRequest(BaseModel):
    text: str
    source_name: Optional[str] = "manual"
    kb_id: Optional[str] = "default"

class QueryRequest(BaseModel):
    question: str
    kb_id: Optional[str] = "default"
    top_k: Optional[int] = 5

# ─────────────────────────────────────────
# CRAWLING
# ─────────────────────────────────────────

async def crawl_single_url(url: str) -> dict:
    """
    Use Crawl4AI — handles JS rendering, extracts clean markdown
    Perfect for Stripe docs which are JS heavy
    """
    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(
            url=url,
            word_count_threshold=50,        # skip tiny pages
            remove_overlay_elements=True,   # remove cookie banners etc
            bypass_cache=False,             # use cache if available
        )
        return {
            "url": url,
            "text": result.markdown,        # clean markdown text
            "success": result.success
        }


async def crawl_multiple_urls(urls: List[str]) -> List[dict]:
    """Crawl multiple URLs concurrently"""
    async with AsyncWebCrawler(verbose=False) as crawler:
        results = await crawler.arun_many(
            urls=urls,
            word_count_threshold=50,
            remove_overlay_elements=True,
        )
        return [
            {"url": r.url, "text": r.markdown, "success": r.success}
            for r in results
        ]


def extract_links_from_page(base_url: str, html: str, url_filter: str = None) -> List[str]:
    """Extract internal links from a crawled page"""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse

    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    links = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Only internal links
        if parsed.netloc != base_domain:
            continue
        # Apply filter if set (e.g. only /docs pages)
        if url_filter and url_filter not in parsed.path:
            continue
        # No anchors
        clean_url = parsed.scheme + "://" + parsed.netloc + parsed.path
        links.add(clean_url)

    return list(links)


def parse_sitemap(sitemap_url: str, url_filter: str = None) -> List[str]:
    """Parse a sitemap.xml and return filtered URLs"""
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(sitemap_url, timeout=10)
    soup = BeautifulSoup(response.text, "xml")
    urls = [loc.text for loc in soup.find_all("loc")]

    if url_filter:
        urls = [u for u in urls if url_filter in u]

    return urls


# ─────────────────────────────────────────
# PROCESSING
# ─────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    """
    Chunk by paragraph first — better for docs
    Falls back to word-based if paragraphs are too large
    """
    # Split on double newlines (paragraph boundaries)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = []
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


def embed(text: str) -> List[float]:
    """Embed text using OpenAI"""
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000]  # safety trim
    )
    return response.data[0].embedding


def store_chunks(chunks: List[str], source: str, kb_id: str) -> int:
    """Embed and store chunks in Chroma"""
    stored = 0
    attempted = 0
    last_error = None

    for i, chunk in enumerate(chunks):
        if len(chunk.strip()) < 50:  # skip tiny chunks
            continue

        attempted += 1
        try:
            chunk_id = str(uuid.uuid4())
            embedding = embed(chunk)
            collection.add(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{
                    "source": source,
                    "kb_id": kb_id,
                    "chunk_index": i
                }]
            )
            stored += 1
        except Exception as exc:
            last_error = exc

    if attempted > 0 and stored == 0 and last_error is not None:
        raise RuntimeError(f"Failed to store any chunks: {last_error}")

    return stored


# ─────────────────────────────────────────
# RETRIEVAL
# ─────────────────────────────────────────

def retrieve_chunks(question: str, kb_id: str, top_k: int) -> List[dict]:
    """Semantic search against knowledge base"""
    query_embedding = embed(question)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"kb_id": kb_id}
    )
    chunks = []
    for i, doc in enumerate(results["documents"][0]):
        chunks.append({
            "text": doc,
            "source": results["metadatas"][0][i]["source"],
            "distance": results["distances"][0][i]
        })
    return chunks


def generate_answer(question: str, chunks: List[dict]) -> str:
    """Generate answer from retrieved chunks using GPT"""
    context = "\n\n---\n\n".join([
        f"Source: {c['source']}\n{c['text']}"
        for c in chunks
    ])

    prompt = f"""You are a precise technical assistant.
Answer the question using ONLY the context provided.
Be specific and technical where needed.
If the answer is not in the context say: "I don't have that information in my knowledge base."
Cite which source the answer came from.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    return response.choices[0].message.content


# ─────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────

@app.post("/ingest/url")
async def ingest_url(request: IngestURLRequest):
    """Ingest a single URL — handles JS rendered pages"""
    try:
        result = await crawl_single_url(request.url)

        if not result["success"] or not result["text"]:
            raise HTTPException(status_code=400, detail=f"Failed to crawl {request.url}")

        chunks = chunk_text(result["text"])
        count = store_chunks(chunks, source=request.url, kb_id=request.kb_id)

        return {
            "status": "success",
            "url": request.url,
            "kb_id": request.kb_id,
            "chunks_stored": count,
            "text_length": len(result["text"])
        }
    except HTTPException:
        raise
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=f"OpenAI quota error while ingesting: {exc}")
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI error while ingesting: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}")


@app.post("/ingest/sitemap")
async def ingest_sitemap(request: IngestSitemapRequest):
    """
    Parse sitemap → crawl all matching URLs → store everything
    Perfect for Stripe docs
    """
    # Step 1 — get all URLs from sitemap
    urls = parse_sitemap(request.sitemap_url, url_filter=request.url_filter)
    urls = urls[:request.max_pages]  # respect limit

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs found in sitemap")

    # Step 2 — crawl all URLs concurrently
    crawl_results = await crawl_multiple_urls(urls)

    # Step 3 — process and store
    total_chunks = 0
    pages_done = 0
    failed = 0

    for result in crawl_results:
        if not result["success"] or not result["text"]:
            failed += 1
            continue
        chunks = chunk_text(result["text"])
        count = store_chunks(chunks, source=result["url"], kb_id=request.kb_id)
        total_chunks += count
        pages_done += 1

    return {
        "status": "success",
        "kb_id": request.kb_id,
        "pages_crawled": pages_done,
        "pages_failed": failed,
        "total_chunks_stored": total_chunks
    }


@app.post("/ingest/text")
async def ingest_text(request: IngestTextRequest):
    """Ingest raw text directly"""
    chunks = chunk_text(request.text)
    count = store_chunks(chunks, source=request.source_name, kb_id=request.kb_id)
    return {
        "status": "success",
        "source": request.source_name,
        "kb_id": request.kb_id,
        "chunks_stored": count
    }


@app.post("/query")
async def query_knowledge(request: QueryRequest):
    """Ask a question — get answer from knowledge base"""
    try:
        chunks = retrieve_chunks(
            question=request.question,
            kb_id=request.kb_id,
            top_k=request.top_k
        )

        if not chunks:
            return {
                "answer": "No relevant information found.",
                "chunks_used": 0,
                "sources": []
            }

        answer = generate_answer(request.question, chunks)

        return {
            "answer": answer,
            "chunks_used": len(chunks),
            "sources": list(set([c["source"] for c in chunks]))
        }
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=f"OpenAI quota error while querying: {exc}")
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI error while querying: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")


@app.get("/health")
async def health():
    return {
        "status": "running",
        "total_chunks": collection.count()
    }
