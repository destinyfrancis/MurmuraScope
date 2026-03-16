"""HK static reference data (census / demographic).

Contains only legitimate static census data from official HK government sources.
All time-series data has been moved to real API downloaders.

Usage::
    python -m backend.data_pipeline.hk_reference_data
"""
from __future__ import annotations

import asyncio

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.hk_reference_data")


# === Population Census Data (official HK Census & Statistics Dept) ===
_CENSUS = {
    1961: {"total": 3129648, "male": 1630378, "female": 1499270},
    1971: {"total": 3936630, "male": 2044655, "female": 1891975},
    1981: {"total": 5183400, "male": 2700780, "female": 2482620},
    1991: {"total": 5752000, "male": 2920000, "female": 2832000},
    1996: {"total": 6217556, "male": 3107259, "female": 3110297},
    2001: {"total": 6708389, "male": 3285344, "female": 3423045},
    2006: {"total": 6864346, "male": 3230000, "female": 3634346},
    2011: {"total": 7071576, "male": 3303015, "female": 3768561},
    2016: {"total": 7336585, "male": 3410605, "female": 3925980},
    2021: {"total": 7413070, "male": 3373560, "female": 4039510},
}

# Age distribution (2021 Census, simplified 5 bands)
_AGE_DIST_2021 = {
    "0-14": 0.113, "15-24": 0.098, "25-44": 0.283,
    "45-64": 0.295, "65+": 0.211,
}

# District population (2021 Census, 18 districts)
_DISTRICT_POP = {
    "中西區": 235953, "灣仔": 166695, "東區": 529603, "南區": 263278,
    "油尖旺": 318522, "深水埗": 405869, "九龍城": 418732, "黃大仙": 425235,
    "觀塘": 648541, "葵青": 495798, "荃灣": 318800, "屯門": 489299,
    "元朗": 668080, "北區": 302657, "大埔": 310879, "沙田": 692015,
    "西貢": 489037, "離島": 184077,
}

# Housing type distribution (2021)
_HOUSING_DIST = {
    "公屋": 0.295, "資助出售房屋": 0.145,
    "私人住宅": 0.525, "臨時／其他": 0.035,
}

# Income bracket distribution (2021 Census)
_INCOME_DIST = {
    "無收入": 0.063, "<$8,000": 0.070, "$8,000-$14,999": 0.155,
    "$15,000-$24,999": 0.235, "$25,000-$39,999": 0.208,
    "$40,000-$59,999": 0.140, "$60,000+": 0.129,
}


async def seed_population_data() -> int:
    """Insert census + demographic data into population_distributions.

    This is the ONLY seeder function. All time-series seeding has been
    removed — real data comes from API downloaders.
    """
    total = 0
    async with get_db() as db:
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pop_unique "
            "ON population_distributions(category, dimension_1, "
            "COALESCE(dimension_2, ''), source_year)"
        )
        # Census total + sex breakdown
        for year, data in _CENSUS.items():
            for dim, val in data.items():
                await db.execute(
                    "INSERT OR REPLACE INTO population_distributions "
                    "(category,dimension_1,dimension_2,count,probability,"
                    "source_year,source_dataset) VALUES (?,?,?,?,?,?,?)",
                    ("population", dim, None, val,
                     val / data["total"], year, "census"),
                )
                total += 1

        # 2021 age distribution
        pop_2021 = _CENSUS[2021]["total"]
        for band, pct in _AGE_DIST_2021.items():
            await db.execute(
                "INSERT OR REPLACE INTO population_distributions "
                "(category,dimension_1,dimension_2,count,probability,"
                "source_year,source_dataset) VALUES (?,?,?,?,?,?,?)",
                ("age_distribution", band, None,
                 int(pop_2021 * pct), pct, 2021, "census"),
            )
            total += 1

        # 2021 district population
        for district, pop in _DISTRICT_POP.items():
            await db.execute(
                "INSERT OR REPLACE INTO population_distributions "
                "(category,dimension_1,dimension_2,count,probability,"
                "source_year,source_dataset) VALUES (?,?,?,?,?,?,?)",
                ("district_population", district, None,
                 pop, pop / pop_2021, 2021, "census"),
            )
            total += 1

        # Housing type
        for htype, pct in _HOUSING_DIST.items():
            await db.execute(
                "INSERT OR REPLACE INTO population_distributions "
                "(category,dimension_1,dimension_2,count,probability,"
                "source_year,source_dataset) VALUES (?,?,?,?,?,?,?)",
                ("housing_type", htype, None,
                 int(pop_2021 * pct), pct, 2021, "census"),
            )
            total += 1

        # Income distribution
        for bracket, pct in _INCOME_DIST.items():
            await db.execute(
                "INSERT OR REPLACE INTO population_distributions "
                "(category,dimension_1,dimension_2,count,probability,"
                "source_year,source_dataset) VALUES (?,?,?,?,?,?,?)",
                ("income_distribution", bracket, None,
                 int(pop_2021 * pct), pct, 2021, "census"),
            )
            total += 1

        await db.commit()
    logger.info("Population data seeded: %d rows", total)
    return total


def main() -> None:
    async def _run() -> None:
        pop = await seed_population_data()
        print(f"Seeded {pop} population/census rows")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
