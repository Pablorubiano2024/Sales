"""ORM models. Import all modules here so Base.metadata sees every table."""

from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent
from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus
from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType, MarketGapSnapshot
from backend.app.models.marketplace import (
    ListingCatalogMatch,
    ListingStatus,
    Marketplace,
    MarketplaceProduct,
)
from backend.app.models.marketplace_credential import MarketplaceCredential
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.order import CustomerShippingStatus, Order, OrderStatus, SaleAlert
from backend.app.models.price_history import PriceHistory
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceProduct, SourceType

__all__ = [
    "Product",
    "Source",
    "SourceProduct",
    "SourceType",
    "Marketplace",
    "MarketplaceProduct",
    "ListingCatalogMatch",
    "MarketplaceCredential",
    "ListingStatus",
    "PriceHistory",
    "Opportunity",
    "OpportunityStatus",
    "Order",
    "OrderStatus",
    "CustomerShippingStatus",
    "SaleAlert",
    "LifecycleStage",
    "OpportunityLifecycleEvent",
    "MarketGapEvent",
    "MarketGapEventType",
    "MarketGapSnapshot",
    "ListingDraft",
    "ListingDraftStatus",
    "AnalyticsEvent",
    "AnalyticsEventType",
]
