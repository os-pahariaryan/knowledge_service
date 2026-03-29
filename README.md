create a .openai_config.json (just fill in the open AI secret key between the quotes after you have generated it.
If you are using something else you may have to change code (as openAI key is set in the env is set by write_env_from_openai_config2.py code)
run Start_server.sh it will bring up the server in the background (and log in server.log)
run driver_ingest_parm.py with the following parameters the repo id for the knowledge base, the URL, the question
python3 driver_ingest.py \
  --kb_id stripe \  (ID to track this also can be used for multitenancy)
  --url "https://docs.stripe.com/payments/checkout" \  (URL)
  --question "How do I build a payments page with Stripe Checkout?" \ (question)
  --top_k 5 (Chunks)
