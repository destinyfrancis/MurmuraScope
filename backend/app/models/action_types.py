"""Extended action type taxonomy for HKSimEngine.

Decouples HKSimEngine's action tracking from OASIS internals, enabling
category-level analytics and action diversity scoring.
"""

from __future__ import annotations

from enum import Enum


class ActionCategory(str, Enum):
    """High-level grouping for agent actions."""

    CONTENT_CREATION = "content_creation"
    ENGAGEMENT = "engagement"
    SOCIAL_MANAGEMENT = "social_management"
    PASSIVE = "passive"
    SEARCH = "search"


class ExtendedActionType(str, Enum):
    """Action types tracked by HKSimEngine.

    Values match OASIS ActionType.value strings for zero-cost mapping.
    """

    # Content creation
    CREATE_POST = "create_post"
    REPOST = "repost"
    QUOTE_POST = "quote_post"
    CREATE_COMMENT = "create_comment"

    # Engagement
    LIKE_POST = "like_post"
    UNLIKE_POST = "unlike_post"
    DISLIKE_POST = "dislike_post"
    LIKE_COMMENT = "like_comment"
    DISLIKE_COMMENT = "dislike_comment"

    # Social management
    FOLLOW = "follow"
    UNFOLLOW = "unfollow"
    MUTE = "mute"
    UNMUTE = "unmute"

    # Passive / lurk
    DO_NOTHING = "do_nothing"
    REFRESH = "refresh"

    # Search & discovery
    SEARCH_POSTS = "search_posts"
    SEARCH_USER = "search_user"
    TREND = "trend"

    # Legacy alias for backward compatibility
    POST = "post"


ACTION_CATEGORY_MAP: dict[ExtendedActionType, ActionCategory] = {
    ExtendedActionType.CREATE_POST: ActionCategory.CONTENT_CREATION,
    ExtendedActionType.REPOST: ActionCategory.CONTENT_CREATION,
    ExtendedActionType.QUOTE_POST: ActionCategory.CONTENT_CREATION,
    ExtendedActionType.CREATE_COMMENT: ActionCategory.CONTENT_CREATION,
    ExtendedActionType.LIKE_POST: ActionCategory.ENGAGEMENT,
    ExtendedActionType.UNLIKE_POST: ActionCategory.ENGAGEMENT,
    ExtendedActionType.DISLIKE_POST: ActionCategory.ENGAGEMENT,
    ExtendedActionType.LIKE_COMMENT: ActionCategory.ENGAGEMENT,
    ExtendedActionType.DISLIKE_COMMENT: ActionCategory.ENGAGEMENT,
    ExtendedActionType.FOLLOW: ActionCategory.SOCIAL_MANAGEMENT,
    ExtendedActionType.UNFOLLOW: ActionCategory.SOCIAL_MANAGEMENT,
    ExtendedActionType.MUTE: ActionCategory.SOCIAL_MANAGEMENT,
    ExtendedActionType.UNMUTE: ActionCategory.SOCIAL_MANAGEMENT,
    ExtendedActionType.DO_NOTHING: ActionCategory.PASSIVE,
    ExtendedActionType.REFRESH: ActionCategory.PASSIVE,
    ExtendedActionType.SEARCH_POSTS: ActionCategory.SEARCH,
    ExtendedActionType.SEARCH_USER: ActionCategory.SEARCH,
    ExtendedActionType.TREND: ActionCategory.SEARCH,
    ExtendedActionType.POST: ActionCategory.CONTENT_CREATION,
}

# Actions that produce content worth logging to simulation_actions
CONTENT_ACTIONS: frozenset[str] = frozenset({
    "create_post", "repost", "quote_post", "create_comment", "post",
})

# Actions that affect the social graph
GRAPH_ACTIONS: frozenset[str] = frozenset({
    "follow", "unfollow", "mute", "unmute",
})

# All actions we want to capture from OASIS trace table
TRACKED_ACTIONS: frozenset[str] = frozenset(
    a.value for a in ExtendedActionType if a != ExtendedActionType.POST
)


def get_category(action_type: str) -> ActionCategory:
    """Map an action type string to its category.

    Falls back to PASSIVE for unknown action types.
    """
    try:
        at = ExtendedActionType(action_type)
        return ACTION_CATEGORY_MAP.get(at, ActionCategory.PASSIVE)
    except ValueError:
        return ActionCategory.PASSIVE
