"""
行业情报采集模块
- 从 RSS 源抓取最新文章
- 提取正文
- LLM 摘要 + 重要性评分
- 排序后推送
"""
import re
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import feedparser
import httpx
from bs4 import BeautifulSoup

from app.llm import chat_json
from app.prompts import SUMMARIZE_PROMPT

# ============ 信息源配置 ============
RSS_SOURCES = [
    {
        "name": "Finextra",
        "url": "https://www.finextra.com/rss/headlines.aspx",
        "type": "rss",
        "category": "行业媒体",
    },
    {
        "name": "The Paypers",
        "url": "https://thepaypers.com/news",
        "type": "html",
        "category": "行业媒体",
    },
]

# HTML 类型的源，直接抓取新闻列表页解析
HTML_SOURCES = [
    {
        "name": "The Paypers",
        "url": "https://thepaypers.com/news",
        "category": "行业媒体",
        "item_selector": "article.article-summary, div.news-item, .article-list article",
        "title_selector": "h2 a, h3 a, .title a",
        "link_selector": "h2 a, h3 a, .title a",
        "summary_selector": "p, .summary, .excerpt",
    },
]

# 文章正文抓取超时
FETCH_TIMEOUT = 20
# 最多抓取多少篇文章进行处理
MAX_ARTICLES = 20
# Top N 推送
TOP_N = 5


def fetch_articles(hours: int = 24) -> List[Dict]:
    """
    从所有信息源抓取最近 N 小时的文章（支持 RSS 和 HTML 列表页）
    返回: [{title, link, source_name, published, summary_rss}]
    """
    articles = []
    cutoff_time = datetime.now() - timedelta(hours=hours)

    for source in RSS_SOURCES:
        source_type = source.get("type", "rss")
        if source_type == "rss":
            articles.extend(_fetch_rss_source(source, cutoff_time))
        elif source_type == "html":
            articles.extend(_fetch_html_source(source, cutoff_time))

    # 去重
    seen = set()
    unique = []
    for a in articles:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)

    print(f"[Intelligence] 共 {len(unique)} 篇有效文章（去重后）")
    return unique


def _fetch_rss_source(source: Dict, cutoff_time: datetime) -> List[Dict]:
    """从单个 RSS 源抓取文章"""
    articles = []
    try:
        print(f"[Intelligence] 正在抓取: {source['name']} (RSS)")
        feed = feedparser.parse(source["url"])

        for entry in feed.entries[:MAX_ARTICLES]:
            published = _parse_published_time(entry)
            if published and published < cutoff_time:
                continue

            article = {
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", "").strip(),
                "source_name": source["name"],
                "source_category": source["category"],
                "published": published.isoformat() if published else "",
                "summary_rss": entry.get("summary", "").strip(),
            }
            article["id"] = hashlib.md5(article["link"].encode()).hexdigest()[:8]
            if article["title"] and article["link"]:
                articles.append(article)

        print(f"[Intelligence] {source['name']} 抓到 {len(articles)} 篇")
    except Exception as e:
        print(f"[Intelligence] {source['name']} 抓取失败: {e}")
    return articles


def _fetch_html_source(source: Dict, cutoff_time: datetime) -> List[Dict]:
    """从 HTML 新闻列表页抓取文章（RSS 不可用时的备选方案）"""
    articles = []
    try:
        print(f"[Intelligence] 正在抓取: {source['name']} (HTML)")
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(source["url"], headers=headers)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # The Paypers 的特殊解析逻辑
        # 查找所有带链接的新闻标题
        count = 0
        for link in soup.select("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            # 过滤：看起来像新闻文章的链接
            if (
                len(text) > 15
                and "/news/" in href
                and not href.endswith("/news")
                and not href.startswith("#")
                and "comment" not in text.lower()
            ):
                # 构造完整 URL
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(source["url"], href)

                article = {
                    "title": _clean_title(text),
                    "link": href,
                    "source_name": source["name"],
                    "source_category": source["category"],
                    "published": "",  # HTML 列表页通常没有明确时间
                    "summary_rss": "",
                }
                article["id"] = hashlib.md5(article["link"].encode()).hexdigest()[:8]
                articles.append(article)
                count += 1
                if count >= MAX_ARTICLES:
                    break

        print(f"[Intelligence] {source['name']} 抓到 {len(articles)} 篇")
    except Exception as e:
        print(f"[Intelligence] {source['name']} HTML 抓取失败: {e}")
    return articles


def _clean_title(title: str) -> str:
    """清理 HTML 抓取的标题，去掉日期、阅读时间等噪音"""
    # 去掉末尾类似 "28 Aug 2026/ 5 min read" 的模式
    cleaned = re.sub(r'\s*\d{1,2}\s+\w{3,}\s+\d{4}.*$', '', title)
    # 去掉 "min read" 等
    cleaned = re.sub(r'\s*\d+\s*min\s*read.*$', '', cleaned, flags=re.I)
    return cleaned.strip()


def _parse_published_time(entry) -> Optional[datetime]:
    """解析 RSS 条目的发布时间"""
    for field in ["published_parsed", "updated_parsed", "created_parsed"]:
        t = entry.get(field)
        if t:
            try:
                return datetime(*t[:6])
            except Exception:
                pass
    return None


def fetch_article_content(url: str) -> str:
    """
    抓取文章正文（简单版本：提取主要文本内容）
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # 移除不需要的标签
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # 尝试找到正文区域
            article = soup.find("article") or soup.find("div", class_=re.compile("article|content|post", re.I))
            if article:
                text = article.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)

            # 清理多余空行
            text = re.sub(r"\n{3,}", "\n\n", text)
            # 限制长度（避免 token 过多）
            if len(text) > 8000:
                text = text[:8000] + "..."

            return text
    except Exception as e:
        print(f"[Intelligence] 正文抓取失败 {url}: {e}")
        return ""


def summarize_article(title: str, content: str) -> dict:
    """
    调用 LLM 生成摘要 + 标签 + 重要性评分
    """
    # 如果内容太短，用 RSS summary 代替
    article_text = content if len(content) > 200 else title + "\n" + content

    prompt = SUMMARIZE_PROMPT.format(article=article_text)

    try:
        result = chat_json(prompt, temperature=0.3, max_tokens=500)
        return result
    except Exception as e:
        print(f"[Intelligence] 摘要生成失败: {e}")
        return {
            "summary_zh": title,
            "tags": ["其他"],
            "importance": 3,
        }


def run_intelligence_daily(hours: int = 24, top_n: int = TOP_N) -> List[Dict]:
    """
    运行完整的情报日报流程：
    抓取 → 摘要 → 排序 → 返回 Top N
    """
    print(f"\n{'='*50}")
    print(f"[Intelligence] 开始生成情报日报（最近 {hours} 小时）")
    print(f"{'='*50}")

    # 1. 抓取文章
    articles = fetch_articles(hours=hours)
    if not articles:
        print("[Intelligence] 没有抓到文章")
        return []

    # 2. 逐篇抓取正文 + 生成摘要
    processed = []
    for i, article in enumerate(articles[:MAX_ARTICLES]):
        print(f"  [{i+1}/{min(len(articles), MAX_ARTICLES)}] 处理: {article['title'][:50]}...")

        # 抓取正文
        content = fetch_article_content(article["link"])

        # 生成摘要
        summary_data = summarize_article(article["title"], content)

        # 合并数据
        item = {
            **article,
            **summary_data,
            "source_url": article["link"],
        }
        processed.append(item)

        # 礼貌延迟
        time.sleep(0.5)

    # 3. 按重要性排序
    processed.sort(key=lambda x: x.get("importance", 0), reverse=True)

    # 4. 返回 Top N
    top_items = processed[:top_n]

    print(f"\n[Intelligence] 完成！共处理 {len(processed)} 篇，Top{top_n} 如下：")
    for i, item in enumerate(top_items, 1):
        print(f"  {i}. [{'⭐'*item.get('importance',0)}] {item.get('title','')[:60]}")

    return top_items


if __name__ == "__main__":
    # 手动测试
    items = run_intelligence_daily(hours=48)
    print(f"\n共 {len(items)} 条 Top 情报")
