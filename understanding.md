
Project does this in two main steps:
1. **It Reads and Remembers (Ingestion):** You give it websites, sitemaps, or raw text (like company policies, documentation, or code). The system reads that text, translates it into a format the AI can understand, and saves it permanently in a local database. 
2. **It Answers Questions (Querying):** When you ask it a question, it quickly searches its database for the exact documents related to your question. It then hands those documents to OpenAI and says: *"Answer the user's question, but ONLY use the information from these documents."*

**The Result:** We get an AI that gives answers based entirely on the specific documentation we fed it.

---

## Technical Overview
A Retrieval-Augmented Generation (RAG) system that ingests text and web pages into a vector database (ChromaDB) and answers queries using OpenAI.

## Code Flow

### 1. Ingestion Flow
1. Crawl webpage (`crawl4ai`) or accept text input.
2. Chunk text into paragraphs.
3. Convert chunks to embeddings using OpenAI.
4. Store chunks and embeddings in local ChromaDB, tagged with a `kb_id`.

### 2. Query Flow
1. Receive question and target `kb_id`.
2. Convert question to an embedding.
3. Perform semantic search in ChromaDB to retrieve relevant chunks.
4. Pass retrieved chunks and question to OpenAI (GPT model) to generate an answer.

## Endpoints Summary
Runs on: `http://127.0.0.1:8000/`

**Ask a Question**
* `POST /query`: Requires `{"question": "...", "kb_id": "...", "top_k": 5}`

**Ingest Data**
* `POST /ingest/url`: Scrapes a single page. Requires `{"url": "...", "kb_id": "..."}`
* `POST /ingest/sitemap`: Scrapes multiple pages. Requires `{"sitemap_url": "...", "kb_id": "...", "max_pages": 50}`
* `POST /ingest/text`: Ingests raw text. Requires `{"text": "...", "source_name": "...", "kb_id": "..."}`

**Utilities**
* `GET /kb_ids`: Returns all existing `kb_id` tags.
* `GET /health`: Returns server status and total stored chunks count.

## How to Use the Endpoints

There are two primary ways to interact with the API while it is running locally:

### 1. Using Swagger UI (Browser)
The easiest way to test the API is through the auto-generated documentation page.
1. Open your browser and go to: `http://127.0.0.1:8000/docs`


### 2. Using cURL (Terminal)
You can test the endpoints directly from your command line using `curl`.

**Example: Ingesting a URL**
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/ingest/url' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "url": "https://docs.stripe.com/payments/checkout",
  "kb_id": "stripe_docs"
}'
```

**Example: Asking a Question**
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/query' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "question": "How do I build a payments page with Stripe Checkout?",
  "kb_id": "stripe_docs",
  "top_k": 5
}'
```
