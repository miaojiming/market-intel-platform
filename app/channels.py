"""
泰国市场情报采集渠道配置
来源：飞书《渠道验证清单》2026-09-03 实测结论，仅纳入 ✅可爬 渠道（ADR 0001）
- Google News RSS 检索式 × 11 组（主力渠道，查询式从存量数据复原）
- 固定源 RSS × 5 个（含本地关键词过滤）
e-GP 政府采购 API 待密钥获批后接入（渠道清单 🔑 待办）
"""

# ============ Google News RSS 检索式 ============
# 单查询最多返回 ~96 条；when 参数控制时间窗，管道按发布时间二次过滤
GOOGLE_NEWS_QUERIES = [
    '"Money20/20 Asia" OR "Bangkok FinTech Fair" OR "Seamless Asia" fintech',
    "PromptPay cross-border QR linkage Thailand",
    'Thailand digital wallet TrueMoney OR ShopeePay OR "Rabbit LINE Pay"',
    'biometric payment OR "AI fraud detection" Thailand bank',
    'tokenization OR "network tokenisation" Southeast Asia card payment',
    "Thailand bank payment partnership OR acquisition OR launch",
    '"Bank of Thailand" regulation payment OR virtual bank OR open banking',
    "Thailand payment summit OR conference fintech 2026",
    "Thailand PDPA enforcement fine data protection",
    "Thailand bank tender OR procurement IT system contract award",
    "Thailand bank replaces OR migrates legacy payment platform",
]

GOOGLE_NEWS_CHANNEL = "Google News RSS"


def google_news_feed_url(query: str, when: str = "2d") -> str:
    from urllib.parse import quote

    return (
        f"https://news.google.com/rss/search?q={quote(query + ' when:' + when, safe='')}"
        "&hl=en-US&gl=US&ceid=US:en"
    )


# ============ 固定源 RSS ============
# filter_keywords: 命中标题或摘要任一关键词才保留（None = 不过滤）
# 依据渠道清单实测：Finextra 需过滤(4/56)、Bangkok Post 命中率~20%、Techsauce 需泰语关键词
FIXED_FEEDS = [
    {
        "name": "Fintech News SG - Thailand",
        "url": "https://fintechnews.sg/tag/thailand/feed/",
        "channel": "Fintech News SG",
        "language": "英语",
        "filter_keywords": None,  # 泰国专题，全收
    },
    {
        "name": "Finextra",
        "url": "https://www.finextra.com/rss/headlines.aspx",
        "channel": "Finextra",
        "language": "英语",
        "filter_keywords": ["thailand", "asean", "southeast asia", "tokeniz", "siam", "bangkok"],
    },
    {
        "name": "Bangkok Post - Business",
        "url": "https://www.bangkokpost.com/rss/data/business.xml",
        "channel": "Bangkok Post",
        "language": "英语",
        "filter_keywords": ["bank", "payment", "fintech", "card", "finance", "digital", "bot "],
    },
    {
        "name": "Bangkok Post - Thailand",
        "url": "https://www.bangkokpost.com/rss/data/thailand.xml",
        "channel": "Bangkok Post",
        "language": "英语",
        "filter_keywords": ["bank", "payment", "fintech", "finance", "digital", "baht", "regulat"],
    },
    {
        "name": "Techsauce",
        "url": "https://techsauce.co/feed",
        "channel": "Techsauce",
        "language": "泰语",
        "filter_keywords": ["ธนาคาร", "จ่าย", "ฟินเทค", "payment", "bank", "fintech"],
    },
]

# 多维表格「采集渠道」单选的全部合法选项（写入前校验，防 SingleSelectFieldConvFail）
VALID_CHANNELS = {
    GOOGLE_NEWS_CHANNEL,
    "Bangkok Post",
    "Fintech News SG",
    "Techsauce",
    "Finextra",
    "e-GP API",
    "手工录入",
}
