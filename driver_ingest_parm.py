import argparse
import requests

API = "http://127.0.0.1:8000"


def ingest_url(url: str, kb_id: str = "default"):
    r = requests.post(
        f"{API}/ingest/url",
        json={
            "url": url,
            "kb_id": kb_id,
            "deep_crawl": False,
            "max_pages": 20,
        },
    )
    print("INGEST STATUS:", r.status_code)
    print(r.json())


def query_kb(question: str, kb_id: str = "default", top_k: int = 5):
    r = requests.post(
        f"{API}/query",
        json={
            "question": question,
            "kb_id": kb_id,
            "top_k": top_k,
        },
    )
    print("QUERY STATUS:", r.status_code)
    print(r.json())


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a URL into the knowledge service and query it."
    )
    parser.add_argument(
        "--kb_id",
        type=str,
        default="default",
        help="Knowledge base ID to store/query under (e.g. 'stripe')",
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="URL to ingest (e.g. https://docs.stripe.com/payments/checkout)",
    )
    parser.add_argument(
        "--question",
        type=str,
        required=True,
        help="Question to ask after ingestion.",
    )
    parser.add_argument(
        "--top_k",
        type=int,
        default=5,
        help="Number of chunks to retrieve for answering.",
    )

    args = parser.parse_args()

    # 1) Ingest the URL into the specified KB
    ingest_url(args.url, args.kb_id)

    # 2) Query that KB with the given question
    query_kb(args.question, args.kb_id, args.top_k)


if __name__ == "__main__":
    main()
