import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def test_web_search_returns_dict():
    from server import web_search
    result = web_search("OpenMP HPC benchmark", n=2)
    assert isinstance(result, dict)
    assert "results" in result or "error" in result

def test_fetch_url_returns_dict():
    from server import fetch_url
    result = fetch_url("https://example.com", max_chars=500)
    assert isinstance(result, dict)
    assert "text" in result or "error" in result

def test_search_arxiv_returns_dict():
    from server import search_arxiv
    result = search_arxiv("OpenMP performance optimization", max_results=2)
    assert isinstance(result, dict)
    assert "papers" in result or "error" in result

def test_web_search_structure():
    from server import web_search
    result = web_search("python performance", n=3)
    if "results" in result and result["results"]:
        for r in result["results"]:
            assert "title" in r
            assert "url" in r
            assert "snippet" in r

def test_fetch_url_error_handling():
    from server import fetch_url
    result = fetch_url("https://this-url-does-not-exist-12345.invalid")
    assert isinstance(result, dict)
    assert "error" in result or "text" in result

def test_search_arxiv_structure():
    from server import search_arxiv
    result = search_arxiv("compiler optimization benchmark", max_results=2)
    if "papers" in result and result["papers"]:
        for p in result["papers"]:
            assert "title" in p
            assert "url" in p
