"""
客户画像生成模块
- 输入公司名 → WebSearch 搜索 → 抓取网页 → LLM 生成画像
"""
import re
import time
import httpx
from bs4 import BeautifulSoup

from typing import List, Dict

from app.llm import chat_json
from app.prompts import PROFILE_PROMPT, SEARCH_QUERY_PROMPT

# 搜索引擎（使用 DuckDuckGo 的 HTML 版，不需要 API Key）
SEARCH_URL = "https://html.duckduckgo.com/html/"
# 每个查询最多取前 N 个结果
MAX_RESULTS_PER_QUERY = 3
# 最多抓取多少个页面
MAX_PAGES = 6
# 请求超时
TIMEOUT = 15


def web_search(query: str, max_results: int = MAX_RESULTS_PER_QUERY) -> List[Dict]:
    """
    使用 DuckDuckGo HTML 版搜索（无需 API Key）
    返回: [{title, url, snippet}]
    """
    results = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                SEARCH_URL,
                data={"q": query, "kl": "us-en"},
                headers=headers,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".result")

            for item in items[:max_results]:
                title_el = item.select_one(".result__title a")
                snippet_el = item.select_one(".result__snippet")
                if title_el:
                    title = title_el.get_text(strip=True)
                    url = title_el.get("href", "")
                    # DuckDuckGo 的链接是跳转链接，提取真实 URL
                    if "uddg=" in url:
                        match = re.search(r"uddg=([^&]+)", url)
                        if match:
                            from urllib.parse import unquote
                            url = unquote(match.group(1))
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    results.append({"title": title, "url": url, "snippet": snippet})
    except Exception as e:
        print(f"[Profile] 搜索失败 '{query}': {e}")

    return results


def fetch_page_text(url: str) -> str:
    """
    抓取网页正文文本
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # 移除噪音标签
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            article = soup.find("article") or soup.find("div", id=re.compile("content|main", re.I))
            if article:
                text = article.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)

            text = re.sub(r"\n{3,}", "\n\n", text)
            # 限制长度
            if len(text) > 5000:
                text = text[:5000] + "..."

            return text
    except Exception as e:
        print(f"[Profile] 页面抓取失败 {url[:60]}: {e}")
        return ""


def generate_search_queries(company: str) -> List[str]:
    """
    让 LLM 生成搜索关键词
    """
    prompt = SEARCH_QUERY_PROMPT.format(company=company)
    try:
        result = chat_json(prompt, temperature=0.3, max_tokens=300)
        queries = result.get("queries", [])
        if queries:
            return queries
    except Exception as e:
        print(f"[Profile] 搜索词生成失败: {e}")

    # 兜底：手动构造关键词
    return [
        f"{company} official website about",
        f"{company} payment acquiring business",
        f"{company} news 2026",
    ]


def generate_profile(company: str) -> dict:
    """
    主流程：输入公司名，输出画像
    """
    print(f"\n{'='*50}")
    print(f"[Profile] 开始生成画像: {company}")
    print(f"{'='*50}")

    # 1. 生成搜索查询
    queries = generate_search_queries(company)
    print(f"[Profile] 搜索关键词: {queries}")

    # 2. 执行搜索 + 收集 URL
    all_results = []
    seen_urls = set()
    for query in queries:
        results = web_search(query)
        for r in results:
            url = r["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

        time.sleep(0.5)

    print(f"[Profile] 搜索到 {len(all_results)} 个不同链接")

    # 3. 抓取页面内容（取前 N 个）
    context_parts = []
    source_urls = []

    for i, result in enumerate(all_results[:MAX_PAGES]):
        url = result["url"]
        print(f"  [{i+1}/{min(len(all_results), MAX_PAGES)}] 抓取: {url[:80]}...")

        text = fetch_page_text(url)
        if text:
            # 加上来源标记
            context_parts.append(
                f"--- 来源 [{i+1}] {result['title']} ({url}) ---\n{text[:3000]}"
            )
            source_urls.append(url)

        time.sleep(0.3)

    if not context_parts:
        print("[Profile] 没有抓取到任何内容")
        return {
            "company_name": company,
            "company_type": "未知",
            "founded": "未知",
            "headquarters": "未知",
            "scale": "未知",
            "core_business": "未找到足够信息",
            "acquiring_business": "未找到足够信息",
            "it_status": "未找到足够信息",
            "recent_news": [],
            "sources": [],
        }

    # 4. 组装上下文
    context_str = "\n\n".join(context_parts)
    # 控制总长度
    if len(context_str) > 12000:
        context_str = context_str[:12000] + "\n...（内容已截断）"

    # 5. 调用 LLM 生成画像
    prompt = PROFILE_PROMPT.format(company=company, context=context_str)

    print("[Profile] 正在生成画像...")
    try:
        profile = chat_json(prompt, temperature=0.3, max_tokens=1500)
    except Exception as e:
        print(f"[Profile] 画像生成失败: {e}")
        return {
            "company_name": company,
            "company_type": "未知",
            "founded": "未知",
            "headquarters": "未知",
            "scale": "未知",
            "core_business": "画像生成失败，请稍后重试",
            "acquiring_business": "画像生成失败",
            "it_status": "画像生成失败",
            "recent_news": [],
            "sources": source_urls,
        }

    # 6. 补充来源 URL
    profile["sources"] = source_urls
    # 确保 company_name 正确
    if not profile.get("company_name"):
        profile["company_name"] = company

    print(f"[Profile] 画像生成完成: {profile.get('company_name')}")
    print(f"  类型: {profile.get('company_type')}")
    print(f"  核心业务: {profile.get('core_business', '')[:50]}...")

    return profile


if __name__ == "__main__":
    # 手动测试
    p = generate_profile("Adyen")
    print("\n最终画像:")
    import json
    print(json.dumps(p, ensure_ascii=False, indent=2))
