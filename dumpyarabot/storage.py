from typing import Any, Dict, Optional

from telegram.ext import ContextTypes

from dumpyarabot.schemas import AcceptOptionsState, PendingReview


class ReviewStorage:
    """Data access layer for managing pending reviews using bot_data persistence."""

    @staticmethod
    def get_pending_reviews(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Get all pending reviews from bot_data."""
        if "pending_reviews" not in context.bot_data:
            context.bot_data["pending_reviews"] = {}
        return context.bot_data["pending_reviews"]

    @staticmethod
    def get_pending_review(
        context: ContextTypes.DEFAULT_TYPE, request_id: str
    ) -> Optional[PendingReview]:
        """Get a specific pending review by request_id."""
        reviews = ReviewStorage.get_pending_reviews(context)
        review_data = reviews.get(request_id)
        if review_data:
            if isinstance(review_data, dict):
                return PendingReview(**review_data)
            else:
                return review_data
        return None

    @staticmethod
    def store_pending_review(
        context: ContextTypes.DEFAULT_TYPE, review: PendingReview
    ) -> None:
        """Store a pending review."""
        reviews = ReviewStorage.get_pending_reviews(context)
        reviews[review.request_id] = review.model_dump()

    @staticmethod
    def remove_pending_review(
        context: ContextTypes.DEFAULT_TYPE, request_id: str
    ) -> bool:
        """Remove a pending review. Returns True if removed, False if not found."""
        reviews = ReviewStorage.get_pending_reviews(context)
        if request_id in reviews:
            del reviews[request_id]
            return True
        return False

    @staticmethod
    def get_options_state(
        context: ContextTypes.DEFAULT_TYPE, request_id: str
    ) -> AcceptOptionsState:
        """Get options state for a request_id, creating default if not exists."""
        if "options_states" not in context.bot_data:
            context.bot_data["options_states"] = {}

        states = context.bot_data["options_states"]
        if request_id not in states:
            states[request_id] = AcceptOptionsState().model_dump()

        return AcceptOptionsState(**states[request_id])

    @staticmethod
    def update_options_state(
        context: ContextTypes.DEFAULT_TYPE, request_id: str, options: AcceptOptionsState
    ) -> None:
        """Update options state for a request_id."""
        if "options_states" not in context.bot_data:
            context.bot_data["options_states"] = {}

        context.bot_data["options_states"][request_id] = options.model_dump()

    @staticmethod
    def remove_options_state(
        context: ContextTypes.DEFAULT_TYPE, request_id: str
    ) -> None:
        """Remove options state for a request_id."""
        if (
            "options_states" in context.bot_data
            and request_id in context.bot_data["options_states"]
        ):
            del context.bot_data["options_states"][request_id]
