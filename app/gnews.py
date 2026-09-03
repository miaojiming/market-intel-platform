"""
Google News RSS 链接解码
RSS 里的 <link> 是 news.google.com 中转链接，需还原为原文 URL 才能入库/抓正文。
算法（对齐 SSujitX/google-news-url-decoder，渠道清单 2026-09-03 实测 53/53 可还原）：
1. GET 中转页 HTML，取 c-wiz > div[jscontroller] 的 data-n-a-sg(签名) / data-n-a-ts(时间戳)
2. POST batchexecute RPC(Fbv4je) 换取原文 URL
失败则返回原中转链接（去重仍可用，正文抓取走浏览器跳转）。
"""
import json
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def decode_google_news_url(url: str, timeout: int = 15) -> str:
    """还原 news.google.com 中转链接为原文 URL；失败返回原链接"""
    if "news.google.com" not in url:
        return url
    try:
        base64_str = _extract_base64(url)
        if not base64_str:
            return url
        params = _fetch_decoding_params(base64_str, timeout)
        if not params:
            return url
        decoded = _decode_via_rpc(base64_str, params["signature"], params["timestamp"], timeout)
        return decoded or url
    except Exception as e:
        print(f"[gnews] 解码失败 {url[:60]}: {e}")
        return url


def _extract_base64(url: str) -> str | None:
    m = re.search(r"/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def _fetch_decoding_params(base64_str: str, timeout: int) -> dict | None:
    """从中转页拿签名与时间戳；articles 形式失败则回退 rss/articles"""
    for path in (f"articles/{base64_str}", f"rss/articles/{base64_str}"):
        try:
            resp = requests.get(
                f"https://news.google.com/{path}",
                headers={"User-Agent": _UA},
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            el = soup.select_one("c-wiz > div[jscontroller]")
            if el and el.get("data-n-a-sg") and el.get("data-n-a-ts"):
                return {"signature": el["data-n-a-sg"], "timestamp": el["data-n-a-ts"]}
        except Exception:
            continue
    return None


def _decode_via_rpc(base64_str: str, signature: str, timestamp: str, timeout: int) -> str | None:
    inner = (
        '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
        '"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
        f'"{base64_str}",{timestamp},"{signature}"]'
    )
    freq = json.dumps([[["Fbv4je", inner]]])
    try:
        resp = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=f"f.req={quote(freq)}",
            headers={
                "User-Agent": _UA,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            timeout=timeout,
        )
        # 响应形如 )]}'\n\n[[...]]，取第二段 JSON
        body = resp.text.split("\n\n")[1]
        parsed = json.loads(body)[:-2]
        return json.loads(parsed[0][2])[1]
    except Exception:
        return None
