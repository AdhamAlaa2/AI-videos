"""Platform publishers. Every publisher defaults to private/draft; posting publicly is opt-in."""

from .base import PostText, PublishError, PublishResult, post_text
from .meta import FacebookPublisher, InstagramPublisher
from .tiktok import TikTokPublisher
from .youtube import YouTubePublisher

PUBLISHERS = {
    "youtube": YouTubePublisher,
    "tiktok": TikTokPublisher,
    "instagram": InstagramPublisher,
    "facebook": FacebookPublisher,
}

__all__ = ["PUBLISHERS", "PostText", "PublishError", "PublishResult", "post_text"]
