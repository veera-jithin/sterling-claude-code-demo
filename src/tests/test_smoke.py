"""
Smoke tests for the Email Job Extraction Agent.

Confirms that all modules import cleanly and core objects can be instantiated
without crashing. No external calls are made.
"""

import pytest


@pytest.mark.smoke
def test_config_imports():
    import config
    assert hasattr(config, "GEMINI_MODEL")
    assert hasattr(config, "GRAPH_API_BASE_URL")
    assert hasattr(config, "MSAL_SCOPES")


@pytest.mark.smoke
def test_extractor_imports():
    from extractor import HtmlExtractor
    extractor = HtmlExtractor()
    assert extractor is not None


@pytest.mark.smoke
def test_extractor_runs_on_empty_string():
    from extractor import HtmlExtractor
    result = HtmlExtractor().extract("")
    assert result == ""


@pytest.mark.smoke
def test_graph_imports():
    from graph import GraphClient, DelegatedAuthProvider, HardcodedTokenAuthProvider
    assert GraphClient is not None


@pytest.mark.smoke
def test_graph_client_instantiates_with_mock_auth(mocker):
    from graph import GraphClient
    mock_auth = mocker.MagicMock()
    mock_auth.get_access_token.return_value = "fake-token"
    client = GraphClient(auth_provider=mock_auth)
    assert client is not None


@pytest.mark.smoke
def test_main_imports():
    import main
    assert hasattr(main, "SYSTEM_PROMPT")
    assert hasattr(main, "EXTRACT_JOBS_FUNCTION")
