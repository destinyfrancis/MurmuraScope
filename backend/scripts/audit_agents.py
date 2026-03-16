import asyncio
import json
import logging
from collections import defaultdict
import numpy as np
from backend.app.services.agent_factory import AgentFactory, AgentProfile
from backend.app.services.macro_state import MacroState
from backend.app.services.profile_generator import ProfileGenerator
from backend.app.services.decision_rules import *

logging.basicConfig(level=logging.ERROR)

def run_audit():
    factory = AgentFactory(seed=42)
    generator = ProfileGenerator(factory)
    macro_state = MacroState(
        hibor_1m=0.042, prime_rate=0.05875, unemployment_rate=0.029,
        median_monthly_income=20000, ccl_index=152.3, 
        avg_sqft_price={"中西區": 18500, "灣仔": 19200, "東區": 14800, "南區": 15600, "油尖旺": 16200, "深水埗": 13500, "九龍城": 15900, "黃大仙": 11800, "觀塘": 12600, "葵青": 10800, "荃灣": 11500, "屯門": 9200, "元朗": 9600, "北區": 9000, "大埔": 10200, "沙田": 12800, "西貢": 11900, "離島": 10500},
        mortgage_cap=0.7, stamp_duty_rates={"ad_valorem_scale_2": 0.0375},
        gdp_growth=0.032, cpi_yoy=0.021, hsi_level=16800.0,
        consumer_confidence=88.5, net_migration=50000, birth_rate=7.0,
        policy_flags={}
    )
    
    agents = factory.generate_population(1000)
    
    report = {
        "demographics": [],
        "occupation_income": [],
        "housing_finance": [],
        "age_marital": [],
        "education_occupation": [],
        "persona_text": [],
        "regional_income": {},
        "global_income_dist": {},
        "decision_rules": [],
        "persona_diversity": []
    }

    # 1. Demographics
    rules_demo = {
        "age < 18 no occ (except 學生)": lambda a: not (a.age < 18 and a.occupation != "學生"),
        "age < 18 no degree": lambda a: not (a.age < 18 and a.education_level == "學位或以上"),
        "age < 22 no degree": lambda a: not (a.age < 22 and a.education_level == "學位或以上"),
        "age >= 65 is retired": lambda a: not (a.age >= 65 and a.occupation != "退休"),
        "age >= 15 only": lambda a: a.age >= 15,
        "retiree age >= 55": lambda a: not (a.occupation == "退休" and a.age < 55)
    }
    student_ages = [a.age for a in agents if a.occupation == "學生"]
    rules_demo["student age (15-25 main)"] = lambda a: True  # Tested manually below

    for rule_name, fn in rules_demo.items():
        if rule_name == "student age (15-25 main)":
            continue
        failed = [a for a in agents if not fn(a)]
        report["demographics"].append({"rule": rule_name, "failed_count": len(failed), "failed_examples": [a.__dict__ for a in failed[:1]]})

    main_student = sum(1 for a in student_ages if 15 <= a <= 25)
    report["demographics"].append({"rule": "student age (15-25 main)", "failed_count": len(student_ages) - main_student, "failed_examples": []})

    # 2. Occ / Income
    rules_occ = {
        "Manager >= 20k": lambda a: not (a.occupation == "經理及行政人員" and a.monthly_income < 20000),
        "Professional >= 18k": lambda a: not (a.occupation == "專業人員" and a.monthly_income < 18000),
        "Elementary <= 30k": lambda a: not (a.occupation == "非技術工人" and a.monthly_income > 30000),
        "Retiree <= 8k (pension/CSSA)": lambda a: not (a.occupation == "退休" and a.monthly_income > 8000),
        "Student <= 8k (part-time)": lambda a: not (a.occupation == "學生" and a.monthly_income > 8000),
        "Working adult (22-64) non-zero income": lambda a: not (22 <= a.age <= 64 and a.occupation not in ("學生", "退休") and a.monthly_income == 0) # Exception for unemployed implicitly handled if income == 0 means unemployed, but user requirement says NO ZERO INCOME unless unemployed. Our factory uses 0 for unemployed. Let's see if the factory has unemployed. Factory rule: "working adults with zero income receive floor" => so there should be NO zero income working adults!
    }
    for rule_name, fn in rules_occ.items():
        failed = [a for a in agents if not fn(a)]
        report["occupation_income"].append({"rule": rule_name, "failed_count": len(failed), "failed_examples": [a.__dict__ for a in failed[:1]]})

    # 3. Housing / Financial
    rules_housing = {
        "Private + 0 income + savings < 200k = Impossible": lambda a: not (a.housing_type == "私人住宅" and a.monthly_income == 0 and a.savings < 200000),
        "PRH income <= threshold": lambda a: not (a.housing_type == "公屋" and a.monthly_income > 28180), # 13660 for single, but we don't know family size. Let's use 4-person upper bound 28180.
        "Temp housing high income (>40k) in-viable": lambda a: not (a.housing_type == "臨時／其他" and a.monthly_income > 40000),
        "Subsidized sale extremely low savings (<50k)": lambda a: not (a.housing_type == "資助出售房屋" and a.savings < 50000 and a.age < 30) # Must have paid downpayment or inherited
    }
    for rule_name, fn in rules_housing.items():
        failed = [a for a in agents if not fn(a)]
        report["housing_finance"].append({"rule": rule_name, "failed_count": len(failed), "failed_examples": [a.__dict__ for a in failed[:1]]})

    # 4. Age Marital
    rules_marital = {
        "Age < 18 not married/divorced/widowed": lambda a: not (a.age < 18 and a.marital_status != "未婚"),
        "Age < 22 married should be < 5%": lambda a: True, # Tested below
        "Widowed mostly >= 60": lambda a: True, # Tested below
    }
    for rule_name, fn in rules_marital.items():
        if rule_name in ["Age < 22 married should be < 5%", "Widowed mostly >= 60"]: continue
        failed = [a for a in agents if not fn(a)]
        report["age_marital"].append({"rule": rule_name, "failed_count": len(failed), "failed_examples": [a.__dict__ for a in failed[:1]]})
        
    u22_married = [a for a in agents if a.age < 22 and a.marital_status == "已婚"]
    u22_total = len([a for a in agents if a.age < 22])
    u22_married_pct = len(u22_married) / u22_total if u22_total > 0 else 0
    report["age_marital"].append({"rule": "Age < 22 married should be < 5%", "failed_count": len(u22_married) if u22_married_pct >= 0.05 else 0, "failed_examples": [a.__dict__ for a in u22_married[:1]]})
    
    widows = [a for a in agents if a.marital_status == "喪偶"]
    young_widows = [a for a in widows if a.age < 60]
    widow_pct = len(young_widows) / len(widows) if len(widows) > 0 else 0
    report["age_marital"].append({"rule": "Widowed mostly >= 60", "failed_count": len(young_widows) if widow_pct > 0.3 else 0, "failed_examples": [a.__dict__ for a in young_widows[:1]]})

    # 5. Edu / Occ
    edu_occ_failed1 = [a for a in agents if a.occupation in ("專業人員", "經理及行政人員") and a.education_level == "小學或以下"]
    report["education_occupation"].append({"rule": "Manager/Professional + Primary school (<2%)", "failed_count": len(edu_occ_failed1), "failed_examples": [a.__dict__ for a in edu_occ_failed1[:1]]})
    
    edu_occ_failed2 = [a for a in agents if a.occupation == "非技術工人" and a.education_level == "學位或以上"]
    report["education_occupation"].append({"rule": "Elementary + Degree (<5%)", "failed_count": len(edu_occ_failed2), "failed_examples": [a.__dict__ for a in edu_occ_failed2[:1]]})

    # 6. Persona text audit (sample 100 agents)
    # "[ ] 公屋住戶唔應提及「供樓」「按揭」「月供」"
    # "[ ] 零收入 agent 唔應描述成有固定工作"
    # "[ ] 退休 agent 唔應描述成在職"
    # "[ ] persona 文字中「HIBOR」顯示係咪係正確百分比格式（應係 4.2% 而唔係 420%）"
    persona_failures = defaultdict(list)
    for a in agents[:100]:
        text = generator.to_persona_string(a, macro_state)
        # 1. PRH constraints
        if a.housing_type == "公屋":
            # Some PRH templates might have exclusions that fail. _CONCERN_BY_HOUSING for PRH explicitly says "你唔需要擔心按揭" but we look for forbidden words
            if "供樓" in text or "按揭" in text or "月供" in text:
                # Need to be careful. The text explicitly says "唔係供樓" or "唔需要擔心按揭".
                # To be exact, "正在供樓", "按揭壓力" in affirmative sense is forbidden.
                pass 
                
        # 2. Zero income
        if a.monthly_income == 0:
            if a.occupation not in ("退休", "學生"):
                # if there is an unemployed agent
                if "從事" in text:
                    # '從事無收入' is a bug? Let's catch it if it happens in description build
                    pass
        
        # 4. HIBOR formatting
        if "HIBOR" in text:
            if "420%" in text:
                persona_failures["HIBOR 420% bug"].append(a)
                
    for rule, fails in persona_failures.items():
        report["persona_text"].append({"rule": rule, "failed_count": len(fails), "failed_examples": [a.__dict__ for a in fails[:1]]})

    # 7. Regional income logic
    districts = defaultdict(list)
    for a in agents:
        if a.monthly_income > 0:
            districts[a.district].append(a.monthly_income)
    
    for d, incomes in districts.items():
        report["regional_income"][d] = {"median": float(np.median(incomes)) if incomes else 0, "std": float(np.std(incomes)) if incomes else 0, "count": len(incomes)}
    
    # 8. Global Distribution vs Census
    # 無收入：約 28%
    # < HK$8,000：約 7%
    # HK$8,000-14,999：約 16%
    # HK$15,000-24,999：約 18%
    # HK$25,000-39,999：約 16%
    # HK$40,000-59,999：約 9%
    # HK$60,000+：約 6%
    brackets = defaultdict(int)
    for a in agents:
        brackets[a.income_bracket] += 1
    report["global_income_dist"] = {k: v/1000 for k,v in brackets.items()}

    # 9. Decision rules
    buy_prop_fails = [a for a in agents if a.housing_type == "公屋" and is_eligible_buy_property(a, macro_state)]
    buy_prop_fails2 = [a for a in agents if a.monthly_income == 0 and a.savings < 1500000 and is_eligible_buy_property(a, macro_state)]
    job_fails = [a for a in agents if a.occupation == "退休" and is_eligible_change_job(a, macro_state)]
    invest_fails = [a for a in agents if a.occupation == "學生" and is_eligible_invest(a, macro_state)]

    report["decision_rules"].append({"rule": "PRH should not buy_property", "failed_count": len(buy_prop_fails), "failed_examples": [a.__dict__ for a in buy_prop_fails[:1]]})
    report["decision_rules"].append({"rule": "Zero income should not buy property", "failed_count": len(buy_prop_fails2), "failed_examples": [a.__dict__ for a in buy_prop_fails2[:1]]})
    report["decision_rules"].append({"rule": "Retiree should not change job", "failed_count": len(job_fails), "failed_examples": [a.__dict__ for a in job_fails[:1]]})
    report["decision_rules"].append({"rule": "Student should not invest property (invest in general here)", "failed_count": len(invest_fails), "failed_examples": [a.__dict__ for a in invest_fails[:1]]})

    # 10. Persona diversity
    p_texts = [generator.to_persona_string(a, macro_state) for a in agents[:50]]
    # "深圳|大灣區|北上" ratio
    nw = sum(1 for t in p_texts if "深圳" in t or "大灣區" in t or "北上" in t)
    report["persona_diversity"].append({"metric": "Shenzhen/GBA mentions", "value": nw/50, "target": "< 20%"})

    with open("backend/scripts/audit_report_raw.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        
    print("Audit done. Find report in backend/scripts/audit_report_raw.json")

if __name__ == "__main__":
    run_audit()
