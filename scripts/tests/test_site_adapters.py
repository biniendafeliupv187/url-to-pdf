import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_adapters import (
    GENERIC_ADAPTER,
    adapter_login_signal,
    content_selectors_for_url,
    get_site_adapter,
)


class TestSiteAdapters:
    def test_returns_geekbang_adapter_for_geekbang_url(self):
        adapter = get_site_adapter("https://time.geekbang.org/column/article/1")
        assert adapter.key == "time.geekbang.org"

    def test_returns_generic_adapter_for_unknown_site(self):
        adapter = get_site_adapter("https://example.com/article")
        assert adapter == GENERIC_ADAPTER

    def test_content_selectors_include_site_specific_and_generic(self):
        selectors = content_selectors_for_url("https://km.netease.com/v4/topic/1")
        assert ".topic-detail" in selectors
        assert "article" in selectors

    def test_adapter_login_signal_uses_url_keywords(self):
        assert adapter_login_signal(
            "https://time.geekbang.org/column/article/1",
            "",
            "https://time.geekbang.org/login",
        ) is True

    def test_adapter_login_signal_uses_body_keywords(self):
        assert adapter_login_signal(
            "https://km.netease.com/v4/topic/1",
            "请完成统一认证并输入验证码",
            "",
        ) is True
