"""Convert AgentProfile to OASIS-compatible persona strings and UserInfo dicts."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import TYPE_CHECKING, Any

from backend.app.services.agent_factory import AgentFactory, AgentProfile
from backend.app.services.macro_state import MacroState

if TYPE_CHECKING:
    from backend.app.domain.base import PromptLocale

logger = logging.getLogger(__name__)

# =========================================================================
# Personality trait descriptions (Chinese)
# =========================================================================

_OPENNESS_DESC: dict[str, str] = {
    "high": "好奇心強、鍾意嘗試新嘢、思想開放",
    "mid": "對新事物持開放態度但亦重視傳統",
    "low": "偏好穩定同熟悉嘅環境、較為保守",
}

_CONSCIENTIOUSNESS_DESC: dict[str, str] = {
    "high": "做嘢有條理、負責任、自律性高",
    "mid": "基本上有計劃但間中都會鬆懈",
    "low": "比較隨性、唔太執著於細節",
}

_EXTRAVERSION_DESC: dict[str, str] = {
    "high": "外向活潑、鍾意社交、精力充沛",
    "mid": "社交同獨處之間取得平衡",
    "low": "偏向內向、鍾意靜靜哋、小圈子社交",
}

_AGREEABLENESS_DESC: dict[str, str] = {
    "high": "和善可親、樂於助人、容易信任人",
    "mid": "待人友善但保持適當距離",
    "low": "直率坦白、較為懷疑、重視自身利益",
}

_NEUROTICISM_DESC: dict[str, str] = {
    "high": "容易緊張焦慮、情緒波動較大",
    "mid": "情緒大致穩定，偶爾會感到壓力",
    "low": "情緒穩定淡定、抗壓能力強",
}


def _trait_level(score: float) -> str:
    if score >= 0.65:
        return "high"
    if score >= 0.35:
        return "mid"
    return "low"


def _describe_personality(profile: AgentProfile) -> str:
    """Return a Chinese personality description from Big Five scores."""
    parts = [
        _OPENNESS_DESC[_trait_level(profile.openness)],
        _CONSCIENTIOUSNESS_DESC[_trait_level(profile.conscientiousness)],
        _EXTRAVERSION_DESC[_trait_level(profile.extraversion)],
        _AGREEABLENESS_DESC[_trait_level(profile.agreeableness)],
        _NEUROTICISM_DESC[_trait_level(profile.neuroticism)],
    ]
    return "；".join(parts)


# =========================================================================
# Housing context
# =========================================================================

_HOUSING_CONTEXT: dict[str, str] = {
    # 注意：描述明確區分「已入住公屋住客」同「喺輪候中嘅申請人」——
    # 公屋住客唔需要供樓、唔可以同時持有私樓，描述必須反映呢個現實。
    "公屋": (
        "住喺公共屋邨，每月向房委會/房協交租（約 HK$1,500-4,000），唔係供樓。"
        "依規定唔可以同時擁有私人物業。"
        "（呢位係已入住公屋住客，唔係喺輪候公屋嘅申請人。）"
    ),
    "資助出售房屋": ("住喺居屋或夾屋，享受政府資助置業計劃，正在供居屋按揭。如欲出售，需先補地價。"),
    "私人住宅": (
        "住喺私人物業——可能係業主（正在供私樓按揭）或租客（交租金）。"
        "HIBOR 浮動直接影響業主月供；租客則面對市場租金壓力。"
    ),
    "臨時／其他": ("居住喺劏房、板間房或其他臨時住所，居住環境唔穩定。上樓（申請公屋）係最迫切嘅需求。"),
}


# =========================================================================
# Property scenario concerns by housing type
# =========================================================================

_CONCERN_BY_HOUSING: dict[str, str] = {
    "公屋": (
        "你住公屋，每個月租金低，但係你一直諗緊係咪值得繼續等上居屋，"
        "定係出去租私樓或者買樓。公屋輪候時間長達5年以上令你好擔心。"
        "你對樓市升跌、按揭利率同政府房屋政策非常敏感。"
    ),
    "資助出售房屋": (
        "你已經上咗居屋，補地價問題係你一大考慮。"
        "你關心私樓樓價走勢同埋居屋市場流轉，"
        "亦留意緊按揭利率變化對你月供嘅影響。"
    ),
    "私人住宅": (
        "你住私樓，係業主定租客對你嘅財務影響好大。"
        "如果係業主，你密切關注樓價同租金走勢，擔心樓價下跌蝕讓；"
        "如果係租客，你煩緊租金高企同找尋更平嘅選擇。"
        "HIBOR高企令供樓負擔加重係你最大憂慮。"
    ),
    "臨時／其他": (
        "你居住環境不穩定，上樓係你最迫切嘅需求。"
        "你密切關注政府房屋政策同公屋申請進展，"
        "對任何影響基層市民嘅樓市新聞都好敏感。"
    ),
}

_INCOME_CONCERN_SUPPLEMENT: dict[str, str] = {
    "無收入": "你暫時冇收入，買樓或租樓對你嚟講係非常沉重嘅負擔。",
    "<$8,000": "月入低微，租金已佔你大部分開支，根本冇能力置業。",
    "$8,000-$14,999": "收入有限，租金或按揭供款佔你收入好大比例，置業夢好遠。",
    "$15,000-$24,999": "收入中下，勉強可以考慮細單位按揭，但壓力測試係難關。",
    "$25,000-$39,999": "收入中等，有機會供得起細單位，但要慳到盡先夠首期。",
    "$40,000-$59,999": "收入尚可，置業係你近期目標，密切留意樓市同按揭優惠。",
    "$60,000+": "收入高，有能力考慮換樓或投資物業，關注資產保值同租金回報。",
}

# Fallback macro context if no MacroState is provided.
_DEFAULT_MACRO_CONTEXT = (
    "【香港宏觀經濟環境（2024-Q1 基準）】\n"
    "一個月 HIBOR：4.20%\n"
    "最優惠利率（P Rate）：5.75%\n"
    "失業率：2.9%\n"
    "每月入息中位數：HK$20,000\n"
    "中原城市領先指數（CCL）：152.3\n"
    "最貴地區（每呎均價）：灣仔（$19,200/呎）、中西區（$18,500/呎）、油尖旺（$16,200/呎）\n"
    "按揭成數上限：70%\n"
    "GDP 增長：3.2%\n"
    "CPI 按年變幅：2.1%\n"
    "恒生指數：16,800\n"
    "消費者信心指數：88.5\n"
    "政策標記：辣招撤銷、高才通計劃、公屋輪候年期 5.5 年\n"
    "\n【外圍因素（2024-Q1 基準）】\n"
    "美聯儲利率（Fed Rate）：5.25-5.50%｜美元/港元：7.82（聯繫匯率）\n"
    "中國GDP增長：5.2%｜人民幣/港元：1.076\n"
    "中國房地產危機嚴重程度：60%｜北水流入：HKD 120億/年\n"
    "台海局勢：相對穩定（風險指數 0.3）\n"
    "中美貿易關係：持續摩擦（緊張指數 0.6）\n"
    "深圳生活成本比率：香港嘅 38%（越低越吸引北上）\n"
    "估計跨境居住港人：約 50,000 人\n"
    "大灣區政策整合進度：55%\n"
)


def _political_stance_desc(profile: AgentProfile) -> str:
    """Return a Cantonese political stance description for the agent.

    Uses ``political_stance`` if present on the profile (Phase 6 field);
    falls back to a neutral description for older profile objects that
    pre-date Phase 6.
    """
    stance: float = getattr(profile, "political_stance", 0.5)
    if stance < 0.3:
        return "你傾向支持現屆政府同建制派立場，認為穩定最重要。"
    if stance > 0.7:
        return "你傾向支持民主派立場，關注公民自由同政制發展。"
    return "你政治立場相對中立，傾向就事論事，唔偏向任何一方。"


def _property_concern(profile: AgentProfile) -> str:
    """Build a property-scenario concern paragraph tailored to the agent."""
    housing_concern = _CONCERN_BY_HOUSING.get(
        profile.housing_type,
        "你密切關注香港樓市動態，對置業、租金及政府政策有自己嘅睇法。",
    )
    income_concern = _INCOME_CONCERN_SUPPLEMENT.get(profile.income_bracket, "")
    return f"{housing_concern}{' ' + income_concern if income_concern else ''}"


# =========================================================================
# Personal concern segmentation — returns 2-3 concerns specific to EACH
# agent so that different profile types write about different topics.
# =========================================================================


def _income_tier(profile: AgentProfile) -> str:
    """Classify income into low / mid / high tier."""
    bracket = profile.income_bracket
    if bracket in ("無收入", "<$8,000", "$8,000-$14,999"):
        return "low"
    if bracket in ("$15,000-$24,999", "$25,000-$39,999"):
        return "mid"
    return "high"  # $40,000-$59,999 or $60,000+


def _get_personal_concerns(profile: AgentProfile) -> str:
    """Return 2-3 personal concern sentences tailored to the agent's segment.

    Segments are derived from housing_type × income_tier × age.  Each branch
    returns concerns that are *specific* to that life situation so agents do
    NOT all repeat the same macro talking points (Shenzhen, HIBOR, GBA).
    """
    housing = profile.housing_type
    tier = _income_tier(profile)
    age = profile.age

    # --- Public housing tenants ---
    if housing == "公屋":
        if tier == "low":
            return (
                "你最關心的係公屋社區嘅日常生活：街市物價、管理費、鄰居關係同小朋友學校。"
                "你唔需要擔心按揭，但係生活費每年都慢慢升，你好擔心長糧或綜援唔夠用。"
                "政府派錢、社區中心服務削減係你最直接關注嘅民生議題。"
            )
        if tier == "mid":
            return (
                "你住公屋但收入算中等，心入面係糾結：係繼續留喺公屋慳租，定係申請綠置居換個好啲嘅居住環境？"
                "你關心子女教育，擔心佢哋將來喺咁貴嘅香港點租樓。"
                "公屋富戶政策係你心中一根刺，唔想被迫遷，但又想住好啲。"
            )
        # high income in public housing (rare edge case)
        return (
            "你係公屋富戶，但因為各種原因未搬走。"
            "你最大壓力係富戶政策可能要你補租甚至遷出，所以一直留意居屋或私樓嘅機會。"
            "你係少數住公屋但有能力投資嘅人，亦密切留意稅務規劃。"
        )

    # --- Subsidised sale (居屋/夾屋) ---
    if housing == "資助出售房屋":
        if age >= 55:
            return (
                "你買咗居屋多年，最關心係退休後嘅醫療開支同強積金夠唔夠用。"
                "居屋傳承問題係你近期要諗清楚嘅事——點樣分配俾子女，要唔要補地價先可以賣？"
                "你對樓市走勢有興趣但唔急於行動，最緊要係健康同子女唔出亂。"
            )
        if tier == "low" or tier == "mid":
            return (
                "你供緊居屋，補地價問題係你一大考慮：係咪要套現轉私樓，定係繼續留喺居屋市場？"
                "月供加埋管理費同雜費，每月開支唔少，你密切留意利率走勢。"
                "你係香港「夾心階層」，賺得唔少但又唔係好有錢，對子女嘅教育開支壓力好大。"
            )
        return (
            "你係高收入居屋業主，係咪值得補地價放售轉換私樓係你常掛心嘅問題。"
            "你更關注投資多元化、稅務規劃，以及私人退休保障（MPF以外嘅安排）。"
            "買多一個私樓作收租用途係你近期積極研究緊嘅方向。"
        )

    # --- Private residential ---
    if housing == "私人住宅":
        if age >= 60:
            return (
                "你係私樓業主多年，退休後最大擔憂係通脹蠶食積蓄同醫療費用不斷攀升。"
                "樓係你最大嘅資產，你一直諗緊係咪縮細樓套現養老，定係留俾子女繼承。"
                "身體狀況係你嘅頭等大事，你會留意長者醫療券、居家安老計劃等政策。"
            )
        if tier == "low":
            return (
                "你租緊私樓，租金開支佔收入好大比例，你每個月都係喺計數——係繼續捱貴租，定係搬去偏遠一點嘅地區？"
                "置業對你嚟講係非常遠嘅目標，光是首期已經要儲好多年。"
                "你最關注嘅係工作穩唔穩定、有冇加薪機會、以及政府有冇租務管制政策。"
            )
        if tier == "mid" and 25 <= age <= 45:
            return (
                "你供緊私樓，HIBOR浮動係你每個月最緊張嘅事——利率升一點，月供就多幾百幾千。"
                "你同伴侶都有工作但夾硬先夠供，生仔嘅問題一直拖住——費用、空間、時間都係障礙。"
                "你擔心萬一失業或生病，供樓壓力會即刻爆煲，所以瘋狂儲緊緊急備用金。"
            )
        # high income private
        return (
            "你係私樓業主，收入穩定，現在緊張緊嘅係樓市走勢——係咪時候換更大嘅樓，定係買多一個收租？"
            "你密切留意按揭利率同銀行優惠，亦關注香港稅制同薪俸稅頂點。"
            "子女嘅國際學校費用係你一大支出，你一直在平衡生活質素同資產累積。"
        )

    # --- Temporary / other (劏房, 籠屋, etc.) ---
    return (
        "你住喺劏房或臨時住所，最迫切嘅需求係上樓——每日都在計算公屋輪候進展，擔心排唔到。"
        "租金貴但環境差，你覺得好唔值，但無選擇。"
        "你最關注政府嘅基層房屋政策，以及有無其他臨時資助計劃幫到你。"
    )


# =========================================================================
# ProfileGenerator
# =========================================================================


class ProfileGenerator:
    """Convert AgentProfile entities to OASIS-compatible persona data."""

    def __init__(
        self,
        agent_factory: AgentFactory | None = None,
        prompt_locale: PromptLocale | None = None,
    ) -> None:
        self._factory = agent_factory or AgentFactory()
        self._locale = prompt_locale

    def to_persona_string(
        self,
        profile: AgentProfile,
        macro_state: MacroState | None = None,
    ) -> str:
        """Generate a detailed Cantonese persona description for OASIS.

        If *macro_state* is provided, a BRIEF macro summary is appended
        (not the full to_prompt_context()) to avoid injecting identical
        Shenzhen/GBA talking points into every single agent persona.
        Personal concerns are segment-specific to maximize topic diversity.
        """
        personality_desc = _describe_personality(profile)
        housing_desc = _HOUSING_CONTEXT.get(profile.housing_type, profile.housing_type)
        username = self._factory.generate_username(profile)
        personal_concerns = _get_personal_concerns(profile)

        income_str = f"HK${profile.monthly_income:,}" if profile.monthly_income > 0 else "暫時無收入"
        savings_str = f"HK${profile.savings:,}"

        # Use brief macro context to avoid 100% Shenzhen/GBA mention rate
        if macro_state is not None:
            macro_brief = macro_state.to_brief_context()
        else:
            macro_brief = "【香港當前經濟背景（一句話）】HIBOR 4.20%、失業率 2.9%、CCL 152.3、GDP增長 3.2%、CPI 2.1%。"

        persona = (
            f"你係一個住喺香港{profile.district}嘅{profile.age}歲"
            f"{'男' if profile.sex == 'M' else '女'}性，"
            f"用戶名「{username}」。\n\n"
            f"【背景】\n"
            f"- 職業：{profile.occupation}\n"
            f"- 學歷：{profile.education_level}\n"
            f"- 婚姻狀況：{profile.marital_status}\n"
            f"- 住屋：{profile.housing_type}（{housing_desc}）\n"
            f"- 每月收入：{income_str}\n"
            f"- 儲蓄：{savings_str}\n"
            f"- 收入組別：{profile.income_bracket}\n\n"
            f"【性格特徵】\n{personality_desc}\n\n"
            f"{macro_brief}\n\n"
            f"【你嘅個人關注點】\n{personal_concerns}\n"
        )

        return persona

    def to_user_info(
        self,
        profile: AgentProfile,
        macro_state: MacroState | None = None,
    ) -> dict[str, Any]:
        """Convert an AgentProfile to an OASIS-compatible UserInfo dict.

        The returned dict follows the OASIS agent schema with all required
        fields for simulation.
        """
        username = self._factory.generate_username(profile)
        persona = self.to_persona_string(profile, macro_state)

        return {
            "id": profile.id,
            "username": username,
            "name": username,
            "agent_type": profile.agent_type,
            "persona": persona,
            "demographics": {
                "age": profile.age,
                "sex": profile.sex,
                "district": profile.district,
                "occupation": profile.occupation,
                "income_bracket": profile.income_bracket,
                "education_level": profile.education_level,
                "marital_status": profile.marital_status,
                "housing_type": profile.housing_type,
            },
            "personality": {
                "openness": profile.openness,
                "conscientiousness": profile.conscientiousness,
                "extraversion": profile.extraversion,
                "agreeableness": profile.agreeableness,
                "neuroticism": profile.neuroticism,
            },
            "financial": {
                "monthly_income": profile.monthly_income,
                "savings": profile.savings,
                "income_bracket": profile.income_bracket,
            },
        }

    def batch_to_user_infos(
        self,
        profiles: list[AgentProfile],
        macro_state: MacroState | None = None,
    ) -> list[dict[str, Any]]:
        """Convert a list of AgentProfiles to OASIS UserInfo dicts."""
        return [self.to_user_info(p, macro_state) for p in profiles]

    def to_oasis_json(
        self,
        profiles: list[AgentProfile],
        macro_state: MacroState | None = None,
    ) -> str:
        """Serialize a list of profiles to OASIS-compatible JSON string."""
        user_infos = self.batch_to_user_infos(profiles, macro_state)
        return json.dumps(user_infos, ensure_ascii=False, indent=2)

    def to_oasis_csv(
        self,
        profiles: list[AgentProfile],
        macro_state: MacroState | None = None,
    ) -> str:
        """Serialize profiles to OASIS agent CSV format.

        The CSV has exactly three columns required by OASIS generate_agents():
          - username   : HK-style Cantonese username
          - description: 1-2 sentence bio (plain text, no newlines)
          - user_char  : Full persona shown to the LLM as a system prompt.
                         Includes demographics, Big Five personality, current
                         macro-economic context (HIBOR, CCL, etc.), property
                         scenario concerns, and instructions to post in
                         Cantonese.

        Args:
            profiles: List of AgentProfile objects to convert.
            macro_state: Optional macro-economic state appended to user_char.

        Returns:
            CSV string with header row followed by one row per profile.
        """
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(["username", "description", "user_char"])

        for profile in profiles:
            username = self._factory.generate_username(profile)
            description = self._build_description(profile)
            user_char = self._build_user_char(profile, macro_state)
            # Strip internal newlines from description to keep CSV clean;
            # user_char may contain newlines — csv.QUOTE_ALL handles quoting.
            writer.writerow([username, description.replace("\n", " "), user_char])

        return output.getvalue()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_description(self, profile: AgentProfile) -> str:
        """Build a concise 1-2 sentence bio for the CSV description column."""
        income_str = f"HK${profile.monthly_income:,}/月" if profile.monthly_income > 0 else "暫時無收入"
        return (
            f"{profile.age}歲{profile.district}居民，"
            f"從事{profile.occupation}，"
            f"月入{income_str}，"
            f"住{profile.housing_type}。"
        )

    def _build_user_char(
        self,
        profile: AgentProfile,
        macro_state: MacroState | None = None,
    ) -> str:
        """Build the full system-prompt persona string for OASIS user_char.

        When a PromptLocale is configured, uses locale-specific language rule,
        personality descriptions, and posting guidelines.  When None, uses
        the existing Cantonese code path (unchanged behavior).

        Includes:
        1. Core demographics (age, sex, district, occupation, income, savings).
        2. Big Five personality description.
        3. Current macro-economic context if macro_state is provided.
        4. Property-scenario specific concerns based on housing type and income.
        5. Explicit language instruction.
        """
        username = self._factory.generate_username(profile)

        income_str = f"HK${profile.monthly_income:,}" if profile.monthly_income > 0 else "暫時無收入"
        savings_str = f"HK${profile.savings:,}"

        # Brief macro background
        if macro_state is not None:
            macro_brief = macro_state.to_brief_context()
        else:
            macro_brief = "【香港當前經濟背景（一句話）】HIBOR 4.20%、失業率 2.9%、CCL 152.3、GDP增長 3.2%、CPI 2.1%。"

        if self._locale:
            # Locale-aware code path: use locale personality descriptions,
            # language rule, and posting guidelines.
            locale = self._locale
            lang_rule = locale.language_rule
            guidelines = locale.posting_guidelines

            # Build personality description from locale personality_descriptions
            def _trait_level(score: float) -> str:
                if score >= 0.65:
                    return "high"
                if score >= 0.35:
                    return "mid"
                return "low"

            # Use mid if not available, fall back to high
            def _desc(trait: str, score: float) -> str:
                trait_dict = locale.personality_descriptions.get(trait, {})
                level = _trait_level(score)
                return trait_dict.get(level, trait_dict.get("high", ""))

            personality_parts = [
                _desc("openness", profile.openness),
                _desc("conscientiousness", profile.conscientiousness),
                _desc("extraversion", profile.extraversion),
                _desc("agreeableness", profile.agreeableness),
                _desc("neuroticism", profile.neuroticism),
            ]
            personality_desc = "; ".join(p for p in personality_parts if p)

            housing_desc = locale.housing_context.get(profile.housing_type, profile.housing_type)

            user_char = (
                f"{lang_rule}\n\n"
                f"You are a resident of {profile.district}, aged {profile.age} "
                f"({'male' if profile.sex == 'M' else 'female'}), "
                f'username: "{username}".\n\n'
                f"[Background]\n"
                f"- Age: {profile.age}\n"
                f"- Occupation: {profile.occupation}\n"
                f"- Education: {profile.education_level}\n"
                f"- Marital Status: {profile.marital_status}\n"
                f"- Housing: {profile.housing_type} ({housing_desc})\n"
                f"- Monthly Income: {income_str}\n"
                f"- Savings: {savings_str}\n"
                f"- Income Bracket: {profile.income_bracket}\n\n"
                f"[Personality]\n{personality_desc}\n\n"
                f"{macro_brief}\n\n"
                f"{guidelines}\n"
            )
            return user_char

        # Cantonese code path (unchanged behavior when no locale provided)
        personality_desc = _describe_personality(profile)
        housing_desc = _HOUSING_CONTEXT.get(profile.housing_type, profile.housing_type)

        # Personal concerns derived from this specific agent's life situation.
        personal_concerns = _get_personal_concerns(profile)

        user_char = (
            f"[語言要求 LANGUAGE RULE] 所有發帖必須用繁體中文（廣東話書面語）。絕對唔准用英文或簡體字。\n\n"
            f"你係一個香港市民，用戶名係「{username}」。\n\n"
            f"【個人背景】\n"
            f"- 年齡：{profile.age}歲\n"
            f"- 性別：{'男' if profile.sex == 'M' else '女'}\n"
            f"- 居住地區：{profile.district}\n"
            f"- 職業：{profile.occupation}\n"
            f"- 學歷：{profile.education_level}\n"
            f"- 婚姻狀況：{profile.marital_status}\n"
            f"- 住屋類型：{profile.housing_type}（{housing_desc}）\n"
            f"- 每月收入：{income_str}\n"
            f"- 總儲蓄：{savings_str}\n"
            f"- 收入組別：{profile.income_bracket}\n\n"
            f"【性格特徵（五大人格）】\n"
            f"{personality_desc}\n\n"
            f"{macro_brief}\n\n"
            f"【你嘅個人關注點】\n"
            f"{personal_concerns}\n\n"
            f"【政治傾向】\n"
            f"{_political_stance_desc(profile)}\n\n"
            f"【社交媒體行為】\n"
            f"- 你主要使用 Facebook 同 Instagram。\n"
            f"- 喺 Facebook，你會加入各種群組（例如地區群組、興趣群組），\n"
            f"  發帖分享睇法、回覆其他人嘅帖子、按讚或嬲嬲 react。\n"
            f"- 喺 Instagram，你會發 story 同 post，caption 比較簡短（200字以內），\n"
            f"  用 hashtag、share 朋友嘅 story、follow 有興趣嘅帳號。\n"
            f"- 你有時會喺連登（LIHKG）睇帖但唔一定會出聲。\n\n"
            f"【發帖指引】\n"
            f"- 【強制】必須用繁體中文廣東話書面語發帖。英文、簡體字一律唔准用。\n"
            f"- 永遠用香港廣東話（書面語夾口語）發帖，唔好用普通話或英文。\n"
            f"- 發帖要反映你嘅真實背景、財務狀況同性格。\n"
            f"- 唔好每次都提深圳/大灣區/北上——專注你自己嘅個人關注點同生活狀況。\n"
            f"  只係你個人情況真係涉及跨境生活或移民，先可以提相關話題。\n"
            f"- 帖子要自然、有情緒、貼地，就好似真係香港人喺 Facebook/Instagram 討論咁。\n"
            f"- 可以用啲香港網絡用語，例如「係咁㗎」「點解咁㗎」「真係喊笑」等。\n"
            f"- 每次只發一個帖，唔好一次過發多個。\n"
        )
        return user_char

    async def build_persona_with_memory(
        self,
        profile: AgentProfile,
        macro_state: MacroState | None = None,
        memory_context: str = "",
    ) -> str:
        """Build enriched persona string that includes agent memory context.

        This method extends to_persona_string() with memory context injected
        after the macro block. The existing to_persona_string() signature is
        preserved for backward compatibility.

        Args:
            profile: AgentProfile to build persona for.
            macro_state: Optional macro-economic state.
            memory_context: Optional memory context string from AgentMemoryService.

        Returns:
            Full persona string with memory context appended.
        """
        base_persona = self.to_persona_string(profile, macro_state)

        if not memory_context:
            return base_persona

        return f"{base_persona}\n\n{memory_context}"
