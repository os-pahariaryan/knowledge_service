import argparse
import requests

API = "http://127.0.0.1:8000"

def query_kb(question: str, kb_id: str = "stripe_docs", top_k: int = 5):
    r = requests.post(
        f"{API}/query",
        json={
            "question": question,
            "kb_id": kb_id,
            "top_k": top_k,
        },
    )
    print("STATUS:", r.status_code)
    print(r.json())

def main():
    parser = argparse.ArgumentParser(
        description="Query the knowledge service with a question."
    )
    parser.add_argument(
        "--question",
        type=str,
        required=True,
        help="Question to ask the knowledge base.",
    )
    parser.add_argument(
        "--kb_id",
        type=str,
        default="stripe_docs",
        help="Knowledge base ID (default: stripe_docs).",
    )
    parser.add_argument(
        "--top_k",
        type=int,
        default=5,
        help="Number of chunks to retrieve (default: 5).",
    )

    args = parser.parse_args()
    query_kb(args.question, args.kb_id, args.top_k)

if __name__ == "__main__":
    main()
