"""Locale registry for domain packs."""

from backend.app.domain.locales.zh_hk import ZH_HK_LOCALE, ZH_HK_SENTIMENT, HK_DEMOGRAPHICS
from backend.app.domain.locales.en_us import EN_US_LOCALE, EN_US_SENTIMENT

LOCALES = {"zh-HK": ZH_HK_LOCALE, "en-US": EN_US_LOCALE}
SENTIMENT_LEXICONS = {"zh-HK": ZH_HK_SENTIMENT, "en-US": EN_US_SENTIMENT}
