"""
泰国市场情报采集渠道配置
来源：飞书《渠道验证清单》2026-09-03 实测结论，仅纳入 ✅可爬 渠道（ADR 0001）
- Google News RSS 检索式 × 20 组（全部 Thailand 强制限定，覆盖收单/核心系统/监管/数字银行等角度）
- 固定源 RSS × 5 个（含本地关键词过滤）
e-GP 政府采购 API 待密钥获批后接入（渠道清单 🔑 待办）
"""

# ============ Google News RSS 检索式 ============
# 单查询最多返回 ~96 条；when 参数控制时间窗，管道按发布时间二次过滤
GOOGLE_NEWS_QUERIES = [
    # 收单与支付核心
    "Thailand AND (merchant acquiring OR payment gateway OR point of sale OR POS terminal)",
    "Thailand AND (PromptPay QR OR cross-border payment OR digital wallet OR mobile payment)",
    "Thailand AND (TrueMoney OR ShopeePay OR \"Rabbit LINE Pay\" OR \"AirPay\" OR mPay)",
    # 银行与核心系统
    "Thailand AND (bank payment partnership OR bank acquisition OR bank launch fintech)",
    "Thailand AND (core banking system replacement OR core banking upgrade OR payment platform migration)",
    "Thailand AND (bank tender OR bank procurement OR bank RFP OR bank bidding IT system)",
    # 监管与政策
    'Thailand AND ("Bank of Thailand" OR BOT) AND (regulation OR policy OR guideline OR circular)',
    "Thailand AND (open banking OR open API OR data sharing bank)",
    "Thailand AND (PDPA OR data protection OR data localization OR cybersecurity bank)",
    # 新兴技术与趋势
    "Thailand AND (CBDC OR central bank digital currency OR digital baht)",
    "Thailand AND (virtual bank OR digital bank OR neobank OR digital banking license)",
    "Thailand AND (e-KYC OR digital identity OR biometric verification OR e-KYC payment)",
    "Thailand AND (BNPL OR \"buy now pay later\" OR consumer finance OR installment payment)",
    "Thailand AND (tokenization OR network tokenisation OR card payment security)",
    # 事件与动态
    'Thailand AND (fintech conference OR fintech summit OR "Money20/20" OR "Seamless Asia")',
    "Thailand AND (bank award OR bank ranking OR fintech investment OR funding)",
    # 电商与零售
    "Thailand AND (e-commerce payment OR COD payment OR online checkout OR payment orchestration)",
    "Thailand AND (sme payment OR small business payment OR merchant onboarding)",
    "Thailand AND (cross-border e-commerce OR cross-border trade payment OR remittance)",
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
