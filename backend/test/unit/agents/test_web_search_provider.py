from unittest.mock import MagicMock, patch

import pytest

from yuxi.agents.toolkits.buildin.tools import (
    _all_tool_instances,
    _create_doubao_search,
    _create_tavily_search,
    _extra_registry,
    _register_web_search_tool,
)


def test_doubao_search_missing_key(monkeypatch):
    monkeypatch.delenv("DOUBAO_SEARCH_API_KEY", raising=False)
    doubao = _create_doubao_search()
    res = doubao.invoke({"query": "python"})
    assert res["error"] == "DOUBAO_SEARCH_API_KEY 未配置"
    assert res["results"] == []


def test_doubao_search_success_with_detailed_params(monkeypatch):
    monkeypatch.setenv("DOUBAO_SEARCH_API_KEY", "test_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ResponseMetadata": {},
        "Result": {
            "TimeCost": 150,
            "WebResults": [
                {
                    "Title": "Python 官网",
                    "Url": "https://www.python.org",
                    "Summary": "Python 编程语言官方网站",
                    "RankScore": 0.98,
                    "SiteName": "Python Org",
                    "PublishTime": "2026-01-01T00:00:00+08:00",
                }
            ],
        },
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        doubao = _create_doubao_search()
        res = doubao.invoke(
            {
                "query": "python 3.13",
                "count": 5,
                "time_range": "OneWeek",
                "sites": ["python.org", "github.com"],
                "block_hosts": ["badsite.com"],
                "content_format": "markdown",
            }
        )

        assert res["query"] == "python 3.13"
        assert len(res["results"]) == 1
        item = res["results"][0]
        assert item["title"] == "Python 官网"
        assert item["url"] == "https://www.python.org"
        assert item["content"] == "Python 编程语言官方网站"
        assert item["score"] == 0.98
        assert item["site_name"] == "Python Org"
        assert item["publish_time"] == "2026-01-01T00:00:00+08:00"

        # Verify payload mapping
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["Query"] == "python 3.13"
        assert payload["Count"] == 5
        assert payload["TimeRange"] == "OneWeek"
        assert payload["Filter"]["Sites"] == "python.org|github.com"
        assert payload["Filter"]["BlockHosts"] == "badsite.com"
        assert payload["ContentFormats"] == "markdown"


def test_tavily_search_uses_default_configuration_without_custom_base(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_BASE", raising=False)

    with patch("langchain_tavily.TavilySearch") as tavily_search:
        _create_tavily_search()

    tavily_search.assert_called_once_with(name="web_search")


def test_tavily_search_passes_normalized_custom_base_and_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "  test-key  ")
    monkeypatch.setenv("TAVILY_API_BASE", " https://tavily.example.com/ ")

    with patch("langchain_tavily.TavilySearch") as tavily_search:
        _create_tavily_search()

    tavily_search.assert_called_once_with(
        name="web_search",
        tavily_api_key="test-key",
        api_base_url="https://tavily.example.com",
    )


def test_tavily_search_rejects_custom_base_without_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_BASE", "https://tavily.example.com")

    with pytest.raises(ValueError, match="TAVILY_API_KEY is empty"):
        _create_tavily_search()


def test_register_web_search_tool_provider_selection(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_SEARCH_API_KEY", "key1")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    instances_before = len(_all_tool_instances)

    _register_web_search_tool()

    assert _extra_registry["web_search"].display_name == "豆包 网页搜索"
    assert len(_all_tool_instances) == instances_before + 1
    assert _all_tool_instances[-1].name == "web_search"
