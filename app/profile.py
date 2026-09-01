"""
客户画像生成模块 v2
- 输入公司名 → 构造信息源 URL → 抓取网页 → LLM 生成画像
- 不依赖搜索引擎，直接从高价值信息源抓取，更稳定
"""
import re
import time
import httpx
from bs4 import BeautifulSoup

from typing import List, Dict, Optional

from app.llm import chat_json
from app.prompts import PROFILE_PROMPT

# 信息源 URL 模板
SOURCE_TEMPLATES = [
    # Wikipedia
    {
        "name": "Wikipedia",
        "url_template": "https://en.wikipedia.org/wiki/{company}",
        "priority": 1,
    },
    # 公司官网 About 页
    {
        "name": "官网 About",
        "url_template": "https://www.{company_lower}.com/about",
        "priority": 2,
    },
    # 公司官网首页
    {
        "name": "官网首页",
        "url_template": "https://www.{company_lower}.com/",
        "priority": 2,
    },
]

# 已知的公司域名映射（处理公司名和域名不一致的情况）
KNOWN_DOMAINS = {
    "dbs bank": "dbs.com",
    "hsbc": "hsbc.com",
    "icbc": "icbc.com.cn",
    "china merchants bank": "cmbchina.com",
    "lakala": "lakala.com",
    "fiserv": "fiserv.com",
    "adyen": "adyen.com",
    "stripe": "stripe.com",
    "jpmorgan chase": "jpmorganchase.com",
    "wells fargo": "wellsfargo.com",
    "bank of america": "bankofamerica.com",
    "citibank": "citi.com",
    "global payments": "globalpayments.com",
    "worldpay": "worldpay.com",
    "ncr": "ncr.com",
}

MAX_PAGES = 8
TIMEOUT = 15


def _get_domain(company: str) -> str:
    """获取公司域名"""
    key = company.lower().strip()
    if key in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[key]
    # 默认：公司名去掉空格 + .com
    return f"{company.lower().replace(' ', '')}.com"


def _build_source_urls(company: str) -> List[Dict]:
    """构造待抓取的信息源 URL 列表"""
    company_lower = company.lower().strip()
    domain = _get_domain(company)

    urls = []
    # 1. Wikipedia
    wiki_name = company.replace(" ", "_")
    urls.append(
        {
            "name": "Wikipedia",
            "url": f"https://en.wikipedia.org/wiki/{wiki_name}",
            "priority": 1,
        }
    )

    # 2. 官网相关页面
    urls.append(
        {"name": "官网首页", "url": f"https://www.{domain}/", "priority": 2}
    )
    urls.append(
        {"name": "官网 About", "url": f"https://www.{domain}/about", "priority": 2}
    )
    # 收单/支付业务页面（尝试多个常见路径，失败自动跳过）
    acquiring_paths = [
        "/payments",
        "/merchants",
        "/business",
    ]
    for path in acquiring_paths:
        urls.append(
            {
                "name": "官网收单业务",
                "url": f"https://www.{domain}{path}",
                "priority": 3,
            }
        )

    return urls


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

            article = soup.find("article") or soup.find(
                "div", id=re.compile("content|main", re.I)
            )
            if article:
                text = article.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)

            text = re.sub(r"\n{3,}", "\n\n", text)
            # 限制长度
            if len(text) > 4000:
                text = text[:4000] + "..."

            return text
    except Exception as e:
        print(f"  ⚠️  抓取失败 {url[:60]}: {e}")
        return ""


def generate_profile(company: str) -> dict:
    """
    主流程：输入公司名，输出画像
    """
    print(f"\n{'='*50}")
    print(f"[Profile] 开始生成画像: {company}")
    print(f"{'='*50}")

    # 1. 构造信息源 URL
    sources = _build_source_urls(company)
    print(f"[Profile] 待抓取信息源: {len(sources)} 个")

    # 2. 抓取页面内容
    context_parts = []
    source_urls = []
    source_names = []

    for i, src in enumerate(sources):
        url = src["url"]
        name = src["name"]
        print(f"  [{i+1}/{len(sources)}] 抓取 [{name}]: {url[:70]}...")

        text = fetch_page_text(url)
        if text and len(text) > 200:  # 至少 200 字符才算有效
            context_parts.append(
                f"--- 来源 [{name}] ({url}) ---\n{text[:3000]}"
            )
            source_urls.append(url)
            source_names.append(name)
            print(f"    ✅ 成功，{len(text)} 字符")
        else:
            print(f"    ❌ 内容过少或失败")

        time.sleep(0.3)

    if not context_parts:
        print("[Profile] 没有抓取到有效内容")
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

    print(f"\n[Profile] 成功抓取 {len(context_parts)} 个信息源")

    # 3. 组装上下文
    context_str = "\n\n".join(context_parts)
    if len(context_str) > 10000:
        context_str = context_str[:10000] + "\n...（内容已截断）"

    # 4. 调用 LLM 生成画像
    prompt = PROFILE_PROMPT.format(company=company, context=context_str)

    print("[Profile] 正在生成画像...")
    try:
        profile = chat_json(prompt, temperature=0.3, max_tokens=3000)
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

    # 5. 补充来源 URL
    profile["sources"] = source_urls
    if not profile.get("company_name"):
        profile["company_name"] = company

    print(f"\n[Profile] ✓ 画像生成完成")
    print(f"  公司: {profile.get('company_name')}")
    print(f"  类型: {profile.get('company_type')}")
    print(f"  核心业务: {str(profile.get('core_business', ''))[:60]}...")
    print(f"  收单业务: {str(profile.get('acquiring_business', ''))[:60]}...")
    print(f"  信息来源: {len(source_urls)} 个")

    return profile


if __name__ == "__main__":
    import json

    p = generate_profile("Adyen")
    print("\n最终画像:")
    print(json.dumps(p, ensure_ascii=False, indent=2))
