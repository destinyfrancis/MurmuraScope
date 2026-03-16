"""集中式廣東話 NLP 詞庫 — 情感關鍵詞、句末助詞修飾因子、主題模式。

所有廣東話情感分析模組（action_logger、social_sentiment_processor）均從此
模組匯入，避免重複定義。

設計原則：
- 所有集合為 frozenset（不可變）
- PARTICLE_MODIFIERS 為普通 dict（只讀用途，不應在執行期修改）
- TOPIC_PATTERNS 為 tuple of (compiled Pattern, str)，建立後不可變
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 正面情感關鍵詞（100+ 條）
# 涵蓋標準書面中文、廣東話口語、財經及樓市術語
# ---------------------------------------------------------------------------

POSITIVE_KEYWORDS: frozenset[str] = frozenset([
    # 原有標準書面語
    # 注意：刪除獨立「好」字 — 廣東話常作填充詞（如「好擔心」「好大壓力」），
    # 導致大量負面帖子被誤判為正面。「好」作強化詞已由 _INTENSIFIER_CHARS 處理。
    # 注意：刪除獨立「升」字 — 在財經語境（「HIBOR升」「息率升」「租金升」）代表負面，
    # 但「升職」「爆升」「回升」等複合詞仍保留於下方財經正面術語清單。
    "好消息", "正", "開心", "高興", "讚", "棒", "優", "增長",
    "賺", "贏", "回升", "復蘇", "改善", "樂觀", "期待", "希望", "成功",
    "勝", "強", "穩定", "放寬", "減息", "降息", "撤辣", "利好",
    # 注意：刪除「得」— 廣東話常見語法助詞（覺得、唔捨得、過得好），非情感詞
    "超預期", "跑贏", "新高", "反彈", "掂", "靚",

    # 廣東話口語正面詞
    "勁", "正到爆", "抵", "抵買", "筍", "筍盤", "好嘢", "醒", "叻",
    "威", "型", "索", "靚仔", "靚女",
    "開心到飛起", "好彩", "幸運", "發達", "上車", "升職", "加薪",
    "轉運", "行運", "旺",
    "有前途", "有希望", "有得做", "有著數", "有得撈", "穩陣", "實淨",
    "堅", "堅嘢",
    "值得", "抵讚", "神", "勁揪", "犀利", "鬼咁正", "好正", "正嘢",
    "掂晒",

    # 廣東話社交正面詞（來自 social_sentiment_processor）
    "著數", "福利", "支持", "加油", "撐", "頂", "正確", "好玩",
    "方便", "係時候", "進步", "向好", "大好", "讚好", "恭喜",

    # 財經正面術語
    "牛市", "爆升", "炒起", "水漲船高", "升浪", "入市良機", "低撈",
    "派息", "分紅", "季績好", "超越預期", "業績理想",

    # 樓市正面術語
    "上樓", "收樓", "入伙", "供得起", "筍盤出現", "樓價回穩",
    "成交暢旺", "減價促銷",
])

# ---------------------------------------------------------------------------
# 負面情感關鍵詞（100+ 條）
# ---------------------------------------------------------------------------

NEGATIVE_KEYWORDS: frozenset[str] = frozenset([
    # 原有標準書面語
    "壞消息", "跌", "差", "唔好", "擔心", "憂", "慘", "危", "問題", "困難",
    "輸", "蝕", "虧", "損", "下跌", "衰退", "惡化", "悲觀", "失望", "恐",
    "弱", "動盪", "加息", "加辣", "收緊", "危機", "崩潰", "爆煲", "雷",
    "慘烈", "新低", "插水", "唔掂", "串", "衰", "廢",

    # 廣東話口語負面詞
    "仆街", "廢柴", "膠", "戇鳩", "痴線", "黐線", "癲", "垃圾", "渣", "屎",
    "冇得救", "冇希望", "冇前途", "死梗", "死得", "冇眼睇",
    "頂唔順", "受唔住",
    "嬲", "怒", "火遮眼", "嬲到震", "激氣", "唔忿氣", "好嬲", "鬧爆",

    # 財經負面術語
    "熊市", "暴跌", "洗倉", "斬倉", "爆倉", "跳水", "大插",
    "慘過食泥", "蝕到喊", "蝕大本", "血本無歸",
    "負資產", "斷供", "蝕入肉",

    # 樓市負面術語
    "撻訂", "蝕讓", "銀主盤", "劈價", "跌市", "供唔起", "冇人接",

    # 廣東話社交負面詞（來自 social_sentiment_processor）
    "嬲", "坑", "黑心", "無奈", "離譜", "無用",
    "噁心", "可惡", "討厭", "唔係人", "爛", "攞命",
    "冇救", "完蛋", "冧", "伏", "核突", "扮嘢", "呃人",
    "死", "冧莊",

    # 廣東話焦慮／壓力詞（新增：修正正面誤判問題）
    # 這些詞在模擬帖子中出現頻率高，但被「好」填充詞蓋過導致誤判
    "擔心", "好擔心", "好辛苦", "壓力", "壓力大", "好大壓力",
    "供唔起", "點算", "點算好", "頭痛", "好頭痛",
    "焦慮", "攰晒", "好攰", "難過", "唔知點算", "迷惘", "沉重",
    "難熬", "煩惱", "喊", "唔開心", "心痛",
    "心寒", "可惜", "擔驚", "好驚", "心驚", "咋舌", "絕望",
    "好難", "唔夠", "捱", "捱唔起",
    "冇辦法", "好慘", "好差", "跌穿", "跌咗", "負增長",
    "失業", "裁員", "好貴", "負擔",
    "好難頂", "頂唔住", "喘唔到氣", "失眠", "心塞", "難受", "好混亂",
])

# ---------------------------------------------------------------------------
# 中立語氣助詞（不改變情感方向，只加入不確定性）
# ---------------------------------------------------------------------------

NEUTRAL_BOOSTERS: frozenset[str] = frozenset([
    "分析", "認為", "覺得", "估計", "預測", "可能", "或者", "不知",
    "等等", "如果", "假設", "情況",
    "未必", "難講", "睇吓", "諗下", "唔確定",
    # 廣東話不確定表達
    "唔知", "唔清楚", "唔肯定", "唔sure", "睇情況", "見步行步",
    "有排傾", "難說", "點算好",
])

# ---------------------------------------------------------------------------
# 廣東話句末助詞修飾因子
#
# 大於 1.0 → 強調／肯定，放大主導情感分數
# 小於 1.0 → 懷疑／輕描淡寫，拉向中性
# ---------------------------------------------------------------------------

PARTICLE_MODIFIERS: dict[str, float] = {
    "㗎": 1.3,   # 肯定語氣助詞（強斷言）
    "喎": 1.2,   # 驚訝或轉述語氣
    "噃": 1.2,   # 提醒／強調
    "嘞": 1.1,   # 輕度強調／完成感
    "囉": 1.1,   # 無奈接受／理所當然
    "喇": 1.1,   # 完成或變化
    "啫": 0.8,   # 淡化（「只不過」）
    "咋": 0.8,   # 限制（「只係」）
    "啩": 0.7,   # 不確定／猜測
    "卦": 0.7,   # 不確定
    "咩": 0.9,   # 反問／輕度懷疑
    "嘅": 1.0,   # 中性助詞
    "啦": 1.0,   # 中性緩和
    "呀": 1.0,   # 中性感嘆
    "吖": 1.0,   # 中性建議
    "呢": 1.0,   # 指示詞（中性）
}

# ---------------------------------------------------------------------------
# 否定詞前綴（否定後的正面詞 → 負面；否定後的負面詞 → 正面）
# ---------------------------------------------------------------------------

_NEGATION_CHARS: frozenset[str] = frozenset(["唔", "不", "冇", "沒", "非", "無"])

# ---------------------------------------------------------------------------
# 強化詞前綴（放大後接形容詞的情感強度）
# ---------------------------------------------------------------------------

_INTENSIFIER_CHARS: frozenset[str] = frozenset(["好", "超", "極", "真", "太", "幾"])

# ---------------------------------------------------------------------------
# 主題模式（標準主題 + 廣東話口語主題）
# ---------------------------------------------------------------------------

TOPIC_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # 原有標準主題
    (re.compile(r"樓市|樓價|物業|房地產|買樓|租樓|按揭"), "property"),
    (re.compile(r"移民|離港|BNO|英國|加拿大|澳洲"), "emigration"),
    (re.compile(r"股市|港股|恒指|股票|基金"), "stock_market"),
    (re.compile(r"利率|HIBOR|加息|減息|按息"), "interest_rate"),
    (re.compile(r"美國|美聯儲|聯儲局|Fed"), "us_economy"),
    (re.compile(r"中國|內地|大陸|北京|習近平"), "china_policy"),
    (re.compile(r"台灣|台海|兩岸"), "taiwan_strait"),
    (re.compile(r"深圳|大灣區|灣區"), "greater_bay_area"),
    (re.compile(r"通脹|CPI|物價|消費"), "inflation"),
    (re.compile(r"就業|失業|工作|薪酬"), "employment"),
    (re.compile(r"政府|政策|林鄭|李家超|財政預算"), "hk_policy"),
    (re.compile(r"公屋|居屋|房委會|房協"), "public_housing"),

    # 廣東話口語主題
    (re.compile(r"北上|返大陸|過關|高鐵|蓮塘|深圳灣"), "cross_border"),
    (re.compile(r"打工|返工|OT|放工|人工|糧|跳槽|辭職"), "workplace"),
    (re.compile(r"生仔|BB|奶粉|幼稚園|育兒|懷孕|湊仔"), "fertility"),
    (re.compile(r"讀書|大學|DSE|Master|碩士|博士|學位"), "education"),
    (re.compile(r"退休|MPF|強積金|養老|長者|安老"), "retirement"),
    (re.compile(r"食飯|飲茶|酒樓|茶餐廳|外賣|foodpanda"), "lifestyle"),
    (re.compile(r"醫療|睇醫生|公立醫院|急症|排期|門診"), "healthcare"),
    (re.compile(r"交通|塞車|港鐵|巴士|的士|渡輪|隧道"), "transport_daily"),
)


# ---------------------------------------------------------------------------
# 核心情感偵測邏輯（供外部模組匯入）
# ---------------------------------------------------------------------------

def _count_cantonese_negatives(text: str) -> int:
    """統計文本中廣東話負面情感標記的出現次數（不計否定翻轉）。

    用途：提供一個快速計數，供 detect_sentiment() 中「3+ 負面詞強制覆蓋」規則使用。

    Args:
        text: 待分析的文本字串。

    Returns:
        負面關鍵詞出現總次數（同一關鍵詞多次出現分別計算）。
    """
    count = 0
    for kw in NEGATIVE_KEYWORDS:
        idx = text.find(kw)
        while idx != -1:
            count += 1
            idx = text.find(kw, idx + len(kw))
    return count


def detect_sentiment(text: str) -> str:
    """基於規則的廣東話情感偵測（關鍵詞匹配 + 句末助詞 + 否定處理）。

    演算法：
    1. 對每個正面／負面關鍵詞計分，考慮前置否定詞（反轉）及強化詞（+0.5 額外分）
    2. 檢查文本末尾 5 個字符的句末助詞，據 PARTICLE_MODIFIERS 縮放主導分數
    3. 若兩方分數相等 → 中性；否則取較高者

    Args:
        text: 待分析的文本字串。

    Returns:
        "positive"、"negative" 或 "neutral" 其中之一。
    """
    if not text:
        return "neutral"

    pos_score: float = 0.0
    neg_score: float = 0.0

    # --- 步驟 1：關鍵詞計分（含否定與強化處理）---
    for kw in POSITIVE_KEYWORDS:
        idx = text.find(kw)
        while idx != -1:
            # 檢查前置字符是否為否定詞
            negated = idx > 0 and text[idx - 1] in _NEGATION_CHARS
            # 檢查前置字符是否為強化詞
            intensified = idx > 0 and text[idx - 1] in _INTENSIFIER_CHARS

            delta = 1.5 if intensified else 1.0
            if negated:
                neg_score += delta   # 否定正面 → 計入負分
            else:
                pos_score += delta
            idx = text.find(kw, idx + len(kw))

    for kw in NEGATIVE_KEYWORDS:
        idx = text.find(kw)
        while idx != -1:
            negated = idx > 0 and text[idx - 1] in _NEGATION_CHARS
            intensified = idx > 0 and text[idx - 1] in _INTENSIFIER_CHARS

            delta = 1.5 if intensified else 1.0
            if negated:
                pos_score += delta   # 否定負面 → 計入正分
            else:
                neg_score += delta
            idx = text.find(kw, idx + len(kw))

    # --- 步驟 2：句末助詞修飾 ---
    tail = text[-5:] if len(text) >= 5 else text
    particle_multiplier = 1.0
    for particle, multiplier in PARTICLE_MODIFIERS.items():
        if particle in tail:
            # 取最後出現的助詞修飾因子（若有多個，取最強的）
            if multiplier > particle_multiplier or particle_multiplier == 1.0:
                particle_multiplier = multiplier
            break

    if particle_multiplier > 1.1:
        # 強調助詞：放大主導情感分數
        if pos_score >= neg_score:
            pos_score *= particle_multiplier
        else:
            neg_score *= particle_multiplier
    elif particle_multiplier < 0.9:
        # 懷疑助詞：拉向中性（縮小兩方分數差距）
        pos_score *= particle_multiplier
        neg_score *= particle_multiplier

    # --- 步驟 3：中立語氣助詞抵消 ---
    # 若文本含有中立語氣詞（如「唔知」「可能」），且主導方分數差距不大，
    # 則拉向中性（差距閾值：<=1.5 分時被中立詞抵消）
    neutral_hit = any(nb in text for nb in NEUTRAL_BOOSTERS)
    if neutral_hit:
        gap = abs(pos_score - neg_score)
        if gap <= 1.5:
            return "neutral"

    # --- 步驟 4：3+ 負面詞強制覆蓋規則 ---
    # 若文本含有 3 個或以上負面情感標記（不計否定翻轉），
    # 直接判為負面，覆蓋正面關鍵詞（如廣東話填充詞「好」所帶來的虛假正分）。
    # 解決「好擔心」「好大壓力」等焦慮內容被誤判為正面的問題。
    if _count_cantonese_negatives(text) >= 3:
        return "negative"

    # --- 步驟 5：決策 ---
    if pos_score == neg_score:
        return "neutral"
    return "positive" if pos_score > neg_score else "negative"


def extract_topics(text: str) -> list[str]:
    """從文本中提取主題標籤（模式匹配 + Hashtag）。

    Args:
        text: 待分析的文本字串。

    Returns:
        排序後的主題標籤列表。
    """
    _HASHTAG_RE = re.compile(r"#(\w+)")
    topics: set[str] = set()

    for pattern, topic in TOPIC_PATTERNS:
        if pattern.search(text):
            topics.add(topic)

    for tag in _HASHTAG_RE.findall(text):
        topics.add(tag.lower())

    return sorted(topics)
