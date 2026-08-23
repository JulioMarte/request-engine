from datetime import timedelta
import re

from request_engine.modules.discovery.application.errors import DiscoverySearchContractError
from request_engine.modules.discovery.application.queries.search_supply import SearchPublishedSupplyQuery

MAX_RADIUS_METERS = 100_000
MAX_WINDOW = timedelta(days=7)
MAX_RESULTS = 100
MAX_ELIGIBLE_CANDIDATES = 500
_CLASSIFICATION_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def validate_search_query(query: SearchPublishedSupplyQuery) -> None:
    if _CLASSIFICATION_KEY.fullmatch(query.service_classification_key) is None:
        raise DiscoverySearchContractError("service_classification_key is invalid")
    if not -90 <= query.origin_latitude <= 90:
        raise DiscoverySearchContractError("origin_latitude must be between -90 and 90")
    if not -180 <= query.origin_longitude <= 180:
        raise DiscoverySearchContractError("origin_longitude must be between -180 and 180")
    if not 0 < query.radius_meters <= MAX_RADIUS_METERS:
        raise DiscoverySearchContractError(
            f"radius_meters must be between 1 and {MAX_RADIUS_METERS}"
        )
    if query.window_start.utcoffset() is None or query.window_end.utcoffset() is None:
        raise DiscoverySearchContractError("discovery window datetimes must be timezone-aware")
    if query.window_end <= query.window_start:
        raise DiscoverySearchContractError("window_end must be after window_start")
    if query.window_end - query.window_start > MAX_WINDOW:
        raise DiscoverySearchContractError("discovery window cannot exceed 7 days")
    if not 1 <= query.limit <= MAX_RESULTS:
        raise DiscoverySearchContractError(f"limit must be between 1 and {MAX_RESULTS}")
