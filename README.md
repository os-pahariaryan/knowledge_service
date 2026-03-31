---
title: Knowledge Demo
emoji: 📚
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

create a .openai_config.json (just fill in the open AI secret key between the quotes after you have generated it.
If you are using something else you may have to change code (as openAI key is set in the env is set by write_env_from_openai_config2.py code)
run Start_server.sh it will bring up the server in the background (and log in server.log)
run driver_ingest_parm.py with the following parameters the repo id for the knowledge base, the URL, the question
python3 driver_ingest.py \
  --kb_id stripe \  (ID to track this also can be used for multitenancy)
  --url "https://docs.stripe.com/payments/checkout" \  (URL)
  --question "How do I build a payments page with Stripe Checkout?" \ (question)
  --top_k 5 (Chunks)
i have broken up the driver where you can build a persistant ingest store here is how you do it(code in driver_ingest_parms.py)
python chroma_ingest_kb.py \
  --kb_id stripe_docs \
  urllist \
  --url_list stripe_urls.txt  (this is the file that contains all the URLs)
  You can now query the file (driver_query_parms.py)
  python driver_query_parms.py \
  --question "How do I build a payments page with Stripe Checkout?" \
  --kb_id stripe_docs \
  --top_k 5
  So we have broken up the driver into ingest and query (not sure if driver_ingest_parm.py will work anymore)
  Added kb_id (knowledge id on the vector database chroma) endpoint on the server
  you can use index.html to do the knowledge query
