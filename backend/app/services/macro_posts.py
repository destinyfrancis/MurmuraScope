"""Shock post generators for OASIS ManualAction injection."""

from __future__ import annotations

from typing import Any

from backend.app.services.macro_state import (
    MacroState,
    SHOCK_INTEREST_RATE_HIKE,
    SHOCK_PROPERTY_CRASH,
    SHOCK_UNEMPLOYMENT_SPIKE,
    SHOCK_POLICY_CHANGE,
    SHOCK_MARKET_RALLY,
    SHOCK_EMIGRATION_WAVE,
    SHOCK_FED_RATE_HIKE,
    SHOCK_FED_RATE_CUT,
    SHOCK_CHINA_SLOWDOWN,
    SHOCK_CHINA_STIMULUS,
    SHOCK_TAIWAN_STRAIT_TENSION,
    SHOCK_TAIWAN_STRAIT_EASE,
    SHOCK_SHENZHEN_MAGNET,
    SHOCK_GREATER_BAY_BOOST,
    SHOCK_TARIFF_INCREASE,
    SHOCK_SUPPLY_CHAIN_DISRUPTION,
    SHOCK_CHINA_DEMAND_COLLAPSE,
    SHOCK_RCEP_BENEFIT,
)


def _post_interest_rate_hike(state: MacroState) -> str:
    return (
        f"【突發】金管局宣佈跟隨美聯儲加息，"
        f"一個月 HIBOR 升至 {state.hibor_1m:.2%}，"
        f"最優惠利率調整至 {state.prime_rate:.2%}。"
        f"供樓人士每月供款預計增加 5-8%。"
        f"業界預料樓市短期內將受壓，"
        f"CCL 指數現報 {state.ccl_index:.1f}。"
        f"#加息 #香港樓市 #HIBOR"
    )


def _post_property_crash(state: MacroState) -> str:
    return (
        f"【樓市急跌】中原城市領先指數跌至 {state.ccl_index:.1f}，"
        f"創近年新低。多個屋苑錄得蝕讓成交，"
        f"銀行收緊估值。恒指同步下跌至 {state.hsi_level:,.0f} 點。"
        f"市場瀰漫觀望氣氛，業主減價求售。"
        f"#樓市 #CCL #香港地產"
    )


def _post_unemployment_spike(state: MacroState) -> str:
    return (
        f"【經濟警號】統計處公佈最新失業率升至 {state.unemployment_rate:.1%}，"
        f"為近期高位。多個行業裁員潮持續，"
        f"每月入息中位數跌至 HK${state.median_monthly_income:,}。"
        f"政府表示正研究紓困措施。"
        f"#失業率 #香港經濟"
    )


def _post_policy_change(state: MacroState) -> str:
    flags_str = "、".join(
        f"{k}" for k, v in state.policy_flags.items() if v is True
    )
    return (
        f"【施政報告】政府宣佈多項房屋及經濟政策調整。"
        f"按揭成數上限調整至 {state.mortgage_cap:.0%}。"
        f"現行政策：{flags_str or '待公佈'}。"
        f"業界反應不一，市民密切關注。"
        f"#施政報告 #房屋政策 #香港"
    )


def _post_market_rally(state: MacroState) -> str:
    return (
        f"【港股急升】恒生指數大漲至 {state.hsi_level:,.0f} 點，"
        f"成交額破千億。北水持續流入，"
        f"科技股領漲。消費者信心指數回升至 {state.consumer_confidence:.1f}。"
        f"分析師看好後市表現。"
        f"#恒指 #港股 #牛市"
    )


def _post_emigration_wave(state: MacroState) -> str:
    return (
        f"【人口流失】統計處數據顯示淨遷出人數達 {abs(state.net_migration):,} 人。"
        f"多個專業界別出現人才荒，"
        f"部分行業薪酬因供應緊張而上調。"
        f"政府加推「高才通」等計劃吸引人才。"
        f"#移民潮 #人才荒 #香港人口"
    )


def _post_fed_rate_hike(state: MacroState) -> str:
    return (
        f"【美聯儲加息】Fed 宣佈加息，聯邦基金利率升至 {state.fed_rate:.2%}。"
        f"由於聯繫匯率制度，HIBOR 料跟隨升至 {state.hibor_1m:.2%}，"
        f"香港供樓人士供款壓力加重。美元強勢，美元/港元維持 {state.usd_hkd:.2f}。"
        f"分析師警告樓市及港股短期承壓。"
        f"#美聯儲 #加息 #HIBOR #香港樓市"
    )


def _post_fed_rate_cut(state: MacroState) -> str:
    return (
        f"【美聯儲減息】Fed 宣佈減息，聯邦基金利率降至 {state.fed_rate:.2%}。"
        f"香港 HIBOR 料跟隨回落至 {state.hibor_1m:.2%}，"
        f"供樓每月負擔有望減輕。市場情緒轉趨樂觀，"
        f"恒指報 {state.hsi_level:,.0f}。"
        f"#減息 #按揭 #港股 #香港樓市"
    )


def _post_china_slowdown(state: MacroState) -> str:
    return (
        f"【中國經濟放緩】內地最新數據顯示 GDP 增長僅 {state.china_gdp_growth:.1%}，"
        f"低過市場預期。房地產危機持續（嚴重程度 {state.china_property_crisis:.0%}），"
        f"北水流入大幅減少至 {state.northbound_capital_bn:.0f}億港元/年，"
        f"恒指受壓至 {state.hsi_level:,.0f}。香港出口及零售業首當其衝。"
        f"#中國經濟 #內房危機 #港股 #北水"
    )


def _post_china_stimulus(state: MacroState) -> str:
    return (
        f"【中國大規模刺激】內地宣佈新一輪財政刺激措施，"
        f"GDP 增長預期升至 {state.china_gdp_growth:.1%}。"
        f"北水加速南下，恒指急升至 {state.hsi_level:,.0f}。"
        f"內地買家重返香港樓市，CCL 指數報 {state.ccl_index:.1f}。"
        f"#中國刺激 #北水 #港股牛市 #香港樓市"
    )


def _post_taiwan_strait_tension(state: MacroState) -> str:
    risk_desc = (
        "極度緊張" if state.taiwan_strait_risk > 0.7
        else "明顯升溫" if state.taiwan_strait_risk > 0.5
        else "有所升溫"
    )
    return (
        f"【台海局勢{risk_desc}】台海緊張局勢升級，地緣政治風險指數升至 {state.taiwan_strait_risk:.1f}。"
        f"國際資金避險情緒升溫，港股大幅波動，恒指跌至 {state.hsi_level:,.0f}。"
        f"部分港人加速移民考慮，社交媒體熱議離港計劃。"
        f"#台海 #地緣政治 #移民 #香港前景"
    )


def _post_taiwan_strait_ease(state: MacroState) -> str:
    return (
        f"【台海局勢緩和】台海緊張形勢出現緩和跡象，風險指數回落至 {state.taiwan_strait_risk:.1f}。"
        f"市場風險偏好回升，恒指反彈至 {state.hsi_level:,.0f}，"
        f"樓市觀望情緒有所改善。CCL 指數報 {state.ccl_index:.1f}。"
        f"#台海緩和 #港股 #樓市"
    )


def _post_shenzhen_magnet(state: MacroState) -> str:
    return (
        f"【深圳吸引力大增】深圳生活成本僅係香港嘅 {state.shenzhen_cost_ratio:.0%}，"
        f"加上新基建落成同高鐵提速，估計已有 {state.cross_border_residents:,} 名港人選擇跨境居住。"
        f"「北上生活」成港人熱話，深圳租金仍遠低於香港，"
        f"令不少年輕人考慮搬至羅湖、福田返港返工。"
        f"#深圳 #北上生活 #跨境 #大灣區"
    )


def _post_greater_bay_boost(state: MacroState) -> str:
    return (
        f"【大灣區政策重磅出台】政府宣佈大灣區整合新措施，"
        f"政策推進指數升至 {state.greater_bay_policy_score:.0%}。"
        f"北部都會區發展加速，元朗、北區物業估值受惠。"
        f"跨境居住港人增至 {state.cross_border_residents:,}，"
        f"「一小時生活圈」逐漸成真。"
        f"#大灣區 #北部都會區 #元朗 #深圳"
    )


# ---------------------------------------------------------------------------
# B2B post generators (Phase 5)
# ---------------------------------------------------------------------------


def _post_tariff_increase(state: MacroState) -> str:
    return (
        f"【關稅壁壘升級】美國宣佈對中國商品加徵關稅，加權平均關稅率升至 {state.import_tariff_rate:.1%}。"
        f"香港作為轉口港首當其衝，物流成本指數升至 {state.export_logistics_cost:.2f}。"
        f"出口導向型企業面臨利潤壓縮，部分考慮轉移產能至東南亞。"
        f"#關稅 #貿易戰 #香港出口"
    )


def _post_supply_chain_disruption(state: MacroState) -> str:
    return (
        f"【供應鏈中斷】全球供應鏈出現嚴重中斷（嚴重程度 {state.supply_chain_disruption:.0%}），"
        f"物流成本急升至 {state.export_logistics_cost:.2f} 倍。"
        f"依賴中國供應鏈嘅香港企業面臨缺貨同延遲交付，"
        f"CPI 按年升至 {state.cpi_yoy:.1%}，市民感受到物價上漲壓力。"
        f"#供應鏈 #物流 #通脹"
    )


def _post_china_demand_collapse(state: MacroState) -> str:
    return (
        f"【中國需求急跌】內地進口需求大幅下跌 {abs(state.china_import_demand):.1%}，"
        f"香港出口企業訂單銳減。中國 GDP 增長放緩至 {state.china_gdp_growth:.1%}，"
        f"恒指受壓跌至 {state.hsi_level:,.0f}。"
        f"貿易商同物流公司面臨嚴峻考驗。"
        f"#中國需求 #出口 #香港貿易"
    )


def _post_rcep_benefit(state: MacroState) -> str:
    return (
        f"【RCEP 紅利釋放】區域全面經濟夥伴關係協定（RCEP）效益顯現，"
        f"關稅率降至 {state.import_tariff_rate:.1%}，物流成本改善至 {state.export_logistics_cost:.2f}。"
        f"香港企業加速拓展東盟市場，GDP 增長受惠升至 {state.gdp_growth:.1%}。"
        f"分析師看好香港轉口貿易前景。"
        f"#RCEP #東盟 #香港貿易 #自由貿易"
    )


# ---------------------------------------------------------------------------
# Post generator registry
# ---------------------------------------------------------------------------

SHOCK_POST_GENERATORS: dict[str, Any] = {
    SHOCK_INTEREST_RATE_HIKE: _post_interest_rate_hike,
    SHOCK_PROPERTY_CRASH: _post_property_crash,
    SHOCK_UNEMPLOYMENT_SPIKE: _post_unemployment_spike,
    SHOCK_POLICY_CHANGE: _post_policy_change,
    SHOCK_MARKET_RALLY: _post_market_rally,
    SHOCK_EMIGRATION_WAVE: _post_emigration_wave,
    SHOCK_FED_RATE_HIKE: _post_fed_rate_hike,
    SHOCK_FED_RATE_CUT: _post_fed_rate_cut,
    SHOCK_CHINA_SLOWDOWN: _post_china_slowdown,
    SHOCK_CHINA_STIMULUS: _post_china_stimulus,
    SHOCK_TAIWAN_STRAIT_TENSION: _post_taiwan_strait_tension,
    SHOCK_TAIWAN_STRAIT_EASE: _post_taiwan_strait_ease,
    SHOCK_SHENZHEN_MAGNET: _post_shenzhen_magnet,
    SHOCK_GREATER_BAY_BOOST: _post_greater_bay_boost,
    SHOCK_TARIFF_INCREASE: _post_tariff_increase,
    SHOCK_SUPPLY_CHAIN_DISRUPTION: _post_supply_chain_disruption,
    SHOCK_CHINA_DEMAND_COLLAPSE: _post_china_demand_collapse,
    SHOCK_RCEP_BENEFIT: _post_rcep_benefit,
}
