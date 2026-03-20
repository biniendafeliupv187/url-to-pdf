from dataclasses import dataclass
from typing import Optional, Sequence, Tuple
from urllib.parse import urlsplit


GENERIC_CONTENT_SELECTORS: Tuple[str, ...] = (
    "#js_content",
    ".rich_media_content",
    "article",
    "main article",
    '[role="main"] article',
    ".article-content",
    ".post-content",
    ".markdown-body",
)


@dataclass(frozen=True)
class SiteAdapter:
    key: str
    hosts: Tuple[str, ...]
    content_selectors: Tuple[str, ...] = ()
    login_url_keywords: Tuple[str, ...] = ()
    login_body_keywords: Tuple[str, ...] = ()


GENERIC_ADAPTER = SiteAdapter(key="generic", hosts=())


ADAPTERS: Tuple[SiteAdapter, ...] = (
    SiteAdapter(
        key="mp.weixin.qq.com",
        hosts=("mp.weixin.qq.com",),
        content_selectors=(
            "#js_content",
            ".rich_media_content",
            ".rich_media_area_primary",
        ),
    ),
    SiteAdapter(
        key="time.geekbang.org",
        hosts=("time.geekbang.org",),
        content_selectors=(
            ".article-content",
            ".article-detail",
            ".simplebar-content article",
            "main article",
        ),
        login_url_keywords=("login", "passport"),
        login_body_keywords=("请登录", "登录后", "立即登录", "手机号", "验证码"),
    ),
    SiteAdapter(
        key="km.netease.com",
        hosts=("km.netease.com",),
        content_selectors=(
            ".topic-detail",
            ".article-content",
            ".ProseMirror",
            ".ql-editor",
            "article",
        ),
        login_url_keywords=("login", "passport", "sso"),
        login_body_keywords=("统一认证", "继续登录", "验证码", "手机号", "密码"),
    ),
)


def normalize_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def get_site_adapter(url: str) -> SiteAdapter:
    host = normalize_host(url)
    for adapter in ADAPTERS:
        if host in adapter.hosts:
            return adapter
    return GENERIC_ADAPTER


def content_selectors_for_url(url: str) -> Tuple[str, ...]:
    adapter = get_site_adapter(url)
    selectors = list(adapter.content_selectors)
    for selector in GENERIC_CONTENT_SELECTORS:
        if selector not in selectors:
            selectors.append(selector)
    return tuple(selectors)


def adapter_login_signal(url: str, body_text: str, current_url: Optional[str] = None) -> bool:
    adapter = get_site_adapter(url)
    body_text = body_text or ""
    current_url = (current_url or "").lower()
    if any(keyword.lower() in current_url for keyword in adapter.login_url_keywords):
        return True
    return any(keyword in body_text for keyword in adapter.login_body_keywords)
