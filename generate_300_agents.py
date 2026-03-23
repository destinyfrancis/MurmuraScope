import os
import sys

from backend.app.services.agent_factory import AgentFactory
from backend.app.services.profile_generator import ProfileGenerator

factory = AgentFactory()
profile_gen = ProfileGenerator()

print("Generating 300 agents...")
profiles = factory.generate_population(300)
print(f"Generated {len(profiles)} agent profiles")

# Property scenario macro context
MACRO_CTX = """當前香港宏觀環境（2026年3月）：
- HIBOR 1個月：4.2% | 最優惠利率：5.875%
- 中原城市領先指數(CCL)：152.3 | 平均呎價：$12,500
- 失業率：3.1% | 薪酬中位數：$20,000
- GDP增長：2.1% | 通脹：2.3%
- 恒生指數：17,800 | 消費信心：45/100
- 淨移出人口：12,000人/年
- 公屋輪候時間：約6年"""

# Build CSV with property scenario context
os.makedirs('data/sessions/property-300-001', exist_ok=True)

rows = []
rows.append('username,description,user_char')

BIG5_DESC = {
    'openness': {
        'high': '思想開放，喜歡嘗試新事物',
        'mid': '思想中等開放',
        'low': '保守，傾向熟悉嘅做法'
    },
    'conscientiousness': {
        'high': '做事認真細心，有計劃',
        'mid': '做事一般認真',
        'low': '比較隨意，唔太計劃'
    },
    'extraversion': {
        'high': '外向，喜歡社交同分享',
        'mid': '性格中等外向',
        'low': '內向，傾向獨立思考'
    },
    'agreeableness': {
        'high': '友善，容易接受他人意見',
        'mid': '一般友善',
        'low': '獨立，有自己主見'
    },
    'neuroticism': {
        'high': '容易焦慮擔心',
        'mid': '情緒一般穩定',
        'low': '情緒穩定，冷靜'
    }
}

def trait_level(v):
    if v >= 0.7: return 'high'
    elif v >= 0.4: return 'mid'
    else: return 'low'

import csv, io

output = io.StringIO()
writer = csv.writer(output, quoting=csv.QUOTE_ALL)
writer.writerow(['username', 'description', 'user_char'])

for p in profiles:
    personality = (
        f"{BIG5_DESC['openness'][trait_level(p.openness)]}，"
        f"{BIG5_DESC['conscientiousness'][trait_level(p.conscientiousness)]}，"
        f"{BIG5_DESC['extraversion'][trait_level(p.extraversion)]}，"
        f"{BIG5_DESC['neuroticism'][trait_level(p.neuroticism)]}"
    )
    
    income_str = f"月入HK${p.monthly_income:,}" if p.monthly_income else "收入未知"
    savings_str = f"儲蓄約HK${p.savings:,}" if p.savings else ""
    sex_str = "男" if p.sex == "M" else "女"
    
    desc = f"{p.age}歲香港{sex_str}性，{p.occupation}，住{p.district}"
    
    char = f"""你係一位香港市民，以下係你嘅背景：
【個人資料】年齡：{p.age}歲 | 性別：{sex_str} | 居住地區：{p.district}
【職業收入】職業：{p.occupation} | {income_str} | 教育程度：{p.education_level}
【家庭狀況】婚姻：{p.marital_status} | 居住類型：{p.housing_type} | {savings_str}
【性格特質】{personality}

{MACRO_CTX}

【你嘅置業態度】
根據你嘅背景，你對香港買樓有自己嘅睇法。你可能關心：利率走向、樓價升跌、按揭負擔、地區選擇、公屋私樓選擇、移民與否。

【行動指示】
請用廣東話（香港口語書面語）同其他人互動，分享你對香港置業嘅真實想法、擔憂同意見。係正常社交媒體咁自然地討論，可以贊同或反對他人觀點。"""

    writer.writerow([p.oasis_username, desc, char])

csv_path = 'data/sessions/property-300-001/agents.csv'
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write(output.getvalue())

line_count = output.getvalue().count('\n')
print(f"CSV written to {csv_path} ({line_count} lines)")
print("Sample usernames:", [p.oasis_username for p in profiles[:5]])
