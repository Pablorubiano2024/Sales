"""ORM models. Import all modules here so Base.metadata sees every table."""

from backend.app.models.marketplace import ListingStatus, Marketplace, MarketplaceProduct
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.order import CustomerShippingStatus, Order, OrderStatus
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
    "ListingStatus",
    "PriceHistory",
    "Opportunity",
    "OpportunityStatus",
    "Order",
    "OrderStatus",
    "CustomerShippingStatus",
]
