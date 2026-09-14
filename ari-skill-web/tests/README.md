# ari-skill-web/tests

- `test_retrieval_contract.py` covers provider parity, aliases, outage, and
  offline/tamper-resistant cassette replay.
- `test_network_policy.py` covers SSRF, DNS pinning, redirects, media, and size.
- `test_citation_and_rerank.py` covers cycle/budget bounds and explicit model
  provenance.
- `test_server.py` and `test_collect_references.py` cover compatibility tools.

All provider calls use fixed mocks; the test suite never depends on live search.
