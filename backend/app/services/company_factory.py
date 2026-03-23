"""Company profile generator for Phase 5 B2B enterprise simulation.

Generates realistic Hong Kong enterprise profiles calibrated to the actual
HK industry structure (based on 2022 Annual Survey of Companies data).
"""

from __future__ import annotations

import random

from backend.app.models.company import CompanyProfile, CompanyType
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("company_factory")

# ---------------------------------------------------------------------------
# HK industry structure defaults (based on 2022 surveys + HKSAR stats)
# ---------------------------------------------------------------------------

DEFAULT_SECTOR_DIST: dict[str, float] = {
    "import_export": 0.25,
    "finance": 0.18,
    "retail": 0.15,
    "logistics": 0.12,
    "manufacturing": 0.10,
    "tech": 0.12,
    "real_estate": 0.08,
}

DEFAULT_SIZE_DIST: dict[str, float] = {
    "sme": 0.75,
    "mnc": 0.15,
    "startup": 0.10,
}

# ---------------------------------------------------------------------------
# HK company name generation components
# ---------------------------------------------------------------------------

_SURNAME_PARTS: tuple[str, ...] = (
    "利",
    "恒",
    "長",
    "新",
    "永",
    "和",
    "信",
    "達",
    "港",
    "華",
    "鴻",
    "太",
    "中",
    "南",
    "東",
    "億",
    "盛",
    "金",
    "聯",
    "亞",
)

_TYPE_PARTS: dict[str, tuple[str, ...]] = {
    "import_export": ("貿易", "進出口", "國際", "通商", "洋行"),
    "finance": ("金融", "投資", "資本", "財富", "證券"),
    "retail": ("零售", "百貨", "商行", "購物", "超市"),
    "logistics": ("物流", "運輸", "倉儲", "快運", "貨運"),
    "manufacturing": ("製造", "工業", "製品", "工廠", "生產"),
    "tech": ("科技", "數碼", "資訊", "創科", "智能"),
    "real_estate": ("地產", "發展", "建設", "置業", "物業"),
}

_SUFFIX_PARTS: tuple[str, ...] = (
    "有限公司",
    "集團",
    "控股",
    "企業",
    "股份有限公司",
)

# ---------------------------------------------------------------------------
# Sector → company_type mapping
# ---------------------------------------------------------------------------

_SECTOR_TO_TYPE: dict[str, str] = {
    "import_export": CompanyType.TRADER,
    "finance": CompanyType.FINANCE,
    "retail": CompanyType.DISTRIBUTOR,
    "logistics": CompanyType.LOGISTICS,
    "manufacturing": CompanyType.MANUFACTURER,
    "tech": CompanyType.TECH,
    "real_estate": CompanyType.DISTRIBUTOR,
}

# ---------------------------------------------------------------------------
# China exposure by sector (fraction 0–1)
# ---------------------------------------------------------------------------

_CHINA_EXPOSURE: dict[str, float] = {
    "import_export": 0.80,
    "finance": 0.40,
    "retail": 0.45,
    "logistics": 0.60,
    "manufacturing": 0.70,
    "tech": 0.35,
    "real_estate": 0.20,
}

_CHINA_EXPOSURE_NOISE: float = 0.10  # ± stdev for jitter

# ---------------------------------------------------------------------------
# Export ratio by sector
# ---------------------------------------------------------------------------

_EXPORT_RATIO: dict[str, float] = {
    "import_export": 0.75,
    "finance": 0.30,
    "retail": 0.10,
    "logistics": 0.50,
    "manufacturing": 0.65,
    "tech": 0.40,
    "real_estate": 0.05,
}

_EXPORT_RATIO_NOISE: float = 0.08

# ---------------------------------------------------------------------------
# Supply chain position by sector
# ---------------------------------------------------------------------------

_SUPPLY_CHAIN_POSITION: dict[str, str] = {
    "import_export": "midstream",
    "finance": "midstream",
    "retail": "downstream",
    "logistics": "midstream",
    "manufacturing": "upstream",
    "tech": "upstream",
    "real_estate": "downstream",
}

# ---------------------------------------------------------------------------
# Revenue and headcount ranges by size
# ---------------------------------------------------------------------------

_REVENUE_BY_SIZE: dict[str, tuple[int, int]] = {
    "sme": (2_000_000, 100_000_000),  # HKD 2M – 100M
    "mnc": (500_000_000, 10_000_000_000),  # HKD 500M – 10B
    "startup": (200_000, 5_000_000),  # HKD 200K – 5M
}

_EMPLOYEES_BY_SIZE: dict[str, tuple[int, int]] = {
    "sme": (5, 250),
    "mnc": (500, 10_000),
    "startup": (2, 50),
}

# ---------------------------------------------------------------------------
# Commercial district weights (weighted toward high-density business areas)
# ---------------------------------------------------------------------------

_COMMERCIAL_DISTRICT_WEIGHTS: dict[str, float] = {
    "中西區": 0.10,
    "灣仔": 0.09,
    "東區": 0.08,
    "南區": 0.03,
    "油尖旺": 0.10,
    "深水埗": 0.05,
    "九龍城": 0.05,
    "黃大仙": 0.04,
    "觀塘": 0.09,
    "葵青": 0.06,
    "荃灣": 0.05,
    "屯門": 0.04,
    "元朗": 0.04,
    "北區": 0.03,
    "大埔": 0.04,
    "沙田": 0.07,
    "西貢": 0.03,
    "離島": 0.02,
}

# ---------------------------------------------------------------------------
# DB DDL (lazily created)
# ---------------------------------------------------------------------------

_CREATE_COMPANY_PROFILES_SQL = """
CREATE TABLE IF NOT EXISTS company_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    company_name        TEXT    NOT NULL,
    company_type        TEXT    NOT NULL,
    industry_sector     TEXT    NOT NULL,
    company_size        TEXT    NOT NULL,
    district            TEXT,
    supply_chain_position TEXT,
    annual_revenue_hkd  INTEGER,
    employee_count      INTEGER,
    china_exposure      REAL    DEFAULT 0.5,
    export_ratio        REAL    DEFAULT 0.3,
    created_at          TEXT    DEFAULT (datetime('now'))
);
"""

_CREATE_COMPANY_PROFILES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_company_session
    ON company_profiles(session_id);
"""

_CREATE_COMPANY_DECISIONS_SQL = """
CREATE TABLE IF NOT EXISTS company_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    company_id          INTEGER NOT NULL,
    round_number        INTEGER NOT NULL,
    decision_type       TEXT    NOT NULL,
    action              TEXT    NOT NULL,
    reasoning           TEXT,
    confidence          REAL    NOT NULL DEFAULT 0.5,
    impact_employees    INTEGER DEFAULT 0,
    impact_revenue_pct  REAL    DEFAULT 0.0,
    created_at          TEXT    DEFAULT (datetime('now'))
);
"""

_CREATE_COMPANY_DECISIONS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_company_decision_session
    ON company_decisions(session_id, round_number);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weighted_choice(weights: dict[str, float], rng: random.Random) -> str:
    """Select a key from *weights* dict using weighted random sampling."""
    keys = list(weights.keys())
    values = list(weights.values())
    return rng.choices(keys, weights=values, k=1)[0]


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _generate_company_name(sector: str, rng: random.Random) -> str:
    """Generate a Hong Kong–style Traditional Chinese company name."""
    surname = rng.choice(_SURNAME_PARTS)
    type_words = _TYPE_PARTS.get(sector, ("企業",))
    type_word = rng.choice(type_words)
    suffix = rng.choice(_SUFFIX_PARTS)
    return f"{surname}{type_word}{suffix}"


def _jitter(base: float, noise: float, rng: random.Random) -> float:
    """Add Gaussian noise to *base*, clamp to [0, 1]."""
    raw = base + rng.gauss(0, noise)
    return _clamp(raw, 0.0, 1.0)


# ---------------------------------------------------------------------------
# CompanyFactory
# ---------------------------------------------------------------------------


class CompanyFactory:
    """Generate realistic HK enterprise profiles for a simulation session."""

    def __init__(self, rng_seed: int | None = None) -> None:
        self._rng = random.Random(rng_seed)
        self._schema_initialised = False

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def generate_companies(
        self,
        session_id: str,
        count: int = 50,
        sector_distribution: dict[str, float] | None = None,
        size_distribution: dict[str, float] | None = None,
    ) -> list[CompanyProfile]:
        """Generate *count* company profiles for the given session.

        Args:
            session_id: Simulation session UUID.
            count: Number of companies to generate (default 50).
            sector_distribution: Custom {sector: weight} mapping.
                Defaults to ``DEFAULT_SECTOR_DIST``.
            size_distribution: Custom {size: weight} mapping.
                Defaults to ``DEFAULT_SIZE_DIST``.

        Returns:
            List of ``CompanyProfile`` instances (id=0 before DB insert).
        """
        sector_dist = sector_distribution or DEFAULT_SECTOR_DIST
        size_dist = size_distribution or DEFAULT_SIZE_DIST

        # Normalise distributions
        sector_dist = _normalise(sector_dist)
        size_dist = _normalise(size_dist)

        profiles: list[CompanyProfile] = []
        used_names: set[str] = set()

        for _ in range(count):
            sector = _weighted_choice(sector_dist, self._rng)
            size = _weighted_choice(size_dist, self._rng)
            district = _weighted_choice(_COMMERCIAL_DISTRICT_WEIGHTS, self._rng)

            company_type = _SECTOR_TO_TYPE.get(sector, CompanyType.TRADER)
            supply_chain_position = _SUPPLY_CHAIN_POSITION.get(sector, "midstream")

            # Unique company name
            name = _generate_company_name(sector, self._rng)
            attempts = 0
            while name in used_names and attempts < 10:
                name = _generate_company_name(sector, self._rng)
                attempts += 1
            used_names.add(name)

            # Revenue and employees
            rev_lo, rev_hi = _REVENUE_BY_SIZE[size]
            annual_revenue = self._rng.randint(rev_lo, rev_hi)

            emp_lo, emp_hi = _EMPLOYEES_BY_SIZE[size]
            employee_count = self._rng.randint(emp_lo, emp_hi)

            china_exposure = _jitter(
                _CHINA_EXPOSURE.get(sector, 0.5),
                _CHINA_EXPOSURE_NOISE,
                self._rng,
            )
            export_ratio = _jitter(
                _EXPORT_RATIO.get(sector, 0.3),
                _EXPORT_RATIO_NOISE,
                self._rng,
            )

            profiles.append(
                CompanyProfile(
                    id=0,
                    session_id=session_id,
                    company_name=name,
                    company_type=company_type,
                    industry_sector=sector,
                    company_size=size,
                    district=district,
                    supply_chain_position=supply_chain_position,
                    annual_revenue_hkd=annual_revenue,
                    employee_count=employee_count,
                    china_exposure=round(china_exposure, 3),
                    export_ratio=round(export_ratio, 3),
                )
            )

        logger.info("Generated %d company profiles for session=%s", len(profiles), session_id)
        return profiles

    async def store_companies(
        self,
        session_id: str,
        companies: list[CompanyProfile],
    ) -> list[CompanyProfile]:
        """Batch INSERT companies into company_profiles table.

        Args:
            session_id: Simulation session UUID.
            companies: List of ``CompanyProfile`` instances (id ignored).

        Returns:
            List of profiles with DB-assigned ``id`` values.
        """
        await self._ensure_schema()

        rows = [
            (
                c.session_id,
                c.company_name,
                c.company_type,
                c.industry_sector,
                c.company_size,
                c.district,
                c.supply_chain_position,
                c.annual_revenue_hkd,
                c.employee_count,
                c.china_exposure,
                c.export_ratio,
            )
            for c in companies
        ]

        async with get_db() as db:
            await db.executemany(
                """
                INSERT INTO company_profiles
                    (session_id, company_name, company_type, industry_sector,
                     company_size, district, supply_chain_position,
                     annual_revenue_hkd, employee_count, china_exposure, export_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()

            # Fetch back with assigned IDs
            cursor = await db.execute(
                "SELECT * FROM company_profiles WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
            db_rows = await cursor.fetchall()

        stored: list[CompanyProfile] = []
        for row in db_rows:
            stored.append(
                CompanyProfile(
                    id=row["id"],
                    session_id=row["session_id"],
                    company_name=row["company_name"],
                    company_type=row["company_type"],
                    industry_sector=row["industry_sector"],
                    company_size=row["company_size"],
                    district=row["district"] or "",
                    supply_chain_position=row["supply_chain_position"] or "midstream",
                    annual_revenue_hkd=row["annual_revenue_hkd"] or 0,
                    employee_count=row["employee_count"] or 0,
                    china_exposure=row["china_exposure"] or 0.5,
                    export_ratio=row["export_ratio"] or 0.3,
                )
            )

        logger.info("Stored %d companies to DB for session=%s", len(stored), session_id)
        return stored

    async def load_companies(self, session_id: str) -> list[CompanyProfile]:
        """Load all company profiles for *session_id* from DB.

        Args:
            session_id: Simulation session UUID.

        Returns:
            List of ``CompanyProfile`` instances.
        """
        await self._ensure_schema()
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM company_profiles WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
            rows = await cursor.fetchall()

        return [
            CompanyProfile(
                id=row["id"],
                session_id=row["session_id"],
                company_name=row["company_name"],
                company_type=row["company_type"],
                industry_sector=row["industry_sector"],
                company_size=row["company_size"],
                district=row["district"] or "",
                supply_chain_position=row["supply_chain_position"] or "midstream",
                annual_revenue_hkd=row["annual_revenue_hkd"] or 0,
                employee_count=row["employee_count"] or 0,
                china_exposure=row["china_exposure"] or 0.5,
                export_ratio=row["export_ratio"] or 0.3,
            )
            for row in rows
        ]

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _ensure_schema(self) -> None:
        """Create company tables if they do not exist (idempotent)."""
        if self._schema_initialised:
            return
        async with get_db() as db:
            await db.execute(_CREATE_COMPANY_PROFILES_SQL)
            await db.execute(_CREATE_COMPANY_PROFILES_INDEX_SQL)
            await db.execute(_CREATE_COMPANY_DECISIONS_SQL)
            await db.execute(_CREATE_COMPANY_DECISIONS_INDEX_SQL)
            await db.commit()
        self._schema_initialised = True
        logger.debug("Company schema ensured")


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _normalise(dist: dict[str, float]) -> dict[str, float]:
    """Return a copy of *dist* with values normalised to sum to 1.0."""
    total = sum(dist.values())
    if total <= 0:
        raise ValueError("Distribution weights must sum to a positive value")
    return {k: v / total for k, v in dist.items()}
