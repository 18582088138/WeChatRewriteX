"""网络代理回归：离线验证 PAC 路由、优先级及公众号请求错误。"""
import httpx
import pytest

from app.services import http
from app.services.crawl.base import CrawlError
from app.services.crawl.wechat_mp import WechatMpCrawler

URL = "https://mp.weixin.qq.com/s/test"


@pytest.fixture
def windows_network(monkeypatch):
    monkeypatch.delenv("WENSHU_HTTP_PROXY", raising=False)
    monkeypatch.setattr(http.sys, "platform", "win32")
    monkeypatch.setattr(http, "getproxies", lambda: {})
    monkeypatch.setattr(http, "proxy_bypass", lambda host: False)
    from app.services import network_policy
    monkeypatch.setattr(network_policy.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    http.close_clients()
    http._cached_windows_proxy.cache_clear()
    yield
    http.close_clients()
    http._cached_windows_proxy.cache_clear()


def test_pac_request_and_crawler_parse(windows_network, monkeypatch):
    """PAC 路由的请求保留 UA、重定向和超时，并能提取正文/图片。"""
    seen = []
    monkeypatch.setattr(http, "_windows_proxy", lambda url: "http://proxy.example:914")
    original_client = httpx.Client

    def client(**kwargs):
        seen.append(kwargs.copy())
        kwargs.pop("proxy")

        def respond(request):
            assert request.headers["User-Agent"].startswith("Mozilla/")
            return httpx.Response(200, text='''<html><h1 id="activity-name">测试文章</h1>
                <span id="js_name">测试作者</span><div id="js_content"><p>正文内容</p>
                <img data-src="https://mmbiz.qpic.cn/image.jpg" /></div></html>''')

        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(http.httpx, "Client", client)
    article = WechatMpCrawler().fetch(URL)
    assert seen[0]["proxy"] == "http://proxy.example:914"
    assert seen[0]["timeout"] == 30 and seen[0]["follow_redirects"] is False
    assert article.title == "测试文章" and article.author == "测试作者"
    assert "正文内容" in article.markdown
    assert article.images[0].url == "https://mmbiz.qpic.cn/image.jpg"


@pytest.mark.parametrize("proxies,bypass", [({"https": "http://env:8080"}, False),
                                           ({"all": "http://env:8080"}, False),
                                           ({}, True)])
def test_environment_proxy_and_bypass_preserved(windows_network, monkeypatch, proxies, bypass):
    monkeypatch.setattr(http, "getproxies", lambda: proxies)
    monkeypatch.setattr(http, "proxy_bypass", lambda host: bypass)
    monkeypatch.setattr(http, "_windows_proxy", lambda url: pytest.fail("不应读取 PAC"))
    assert http.proxy_for(URL) is None  # 交给 httpx 的环境代理/NO_PROXY 处理。


def test_explicit_proxy_overrides_pac(windows_network, monkeypatch):
    monkeypatch.setenv("WENSHU_HTTP_PROXY", "http://manual:7890")
    monkeypatch.setattr(http, "_windows_proxy", lambda url: pytest.fail("不应读取 PAC"))
    assert http.proxy_for(URL) == "http://manual:7890"


def test_pac_direct_and_cache(windows_network, monkeypatch):
    calls = []
    monkeypatch.setattr(http, "_windows_proxy", lambda url: calls.append(url))
    assert http.proxy_for(URL) is None
    assert http.proxy_for(URL) is None
    assert calls == [URL]


def test_non_windows_uses_default_client(windows_network, monkeypatch):
    monkeypatch.setattr(http.sys, "platform", "linux")
    monkeypatch.setattr(http, "_windows_proxy", lambda url: pytest.fail("不应读取 PAC"))
    assert http.proxy_for(URL) is None


@pytest.mark.parametrize("value,scheme,want", [
    ("proxy.example:914", "https", "http://proxy.example:914"),
    ("http=a:80;https=b:81", "https", "http://b:81"),
    ("http=a:80", "https", None),
])
def test_winhttp_proxy_format(value, scheme, want):
    assert http._proxy_for_scheme(value, scheme) == want


def test_pac_failure_falls_back(windows_network, monkeypatch):
    def failed(url):
        raise OSError("PAC unavailable")
    monkeypatch.setattr(http, "_windows_proxy", failed)
    assert http.proxy_for(URL) is None


def test_wechat_timeout_is_actionable(monkeypatch):
    def failed(*args, **kwargs):
        raise httpx.ConnectTimeout("WinError 10060")
    monkeypatch.setattr(http, "get", failed)
    with pytest.raises(CrawlError, match="系统代理") as error:
        WechatMpCrawler().fetch(URL)
    assert isinstance(error.value.__cause__, httpx.ConnectTimeout)
