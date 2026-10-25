"""Application-wide paid-call gate supplied by the integrator.

Both stylist transports must receive the SAME centralized guard as other app
providers. No default implementation authorizes spending. The guard must obtain
per-action permission, know a conservative upper cost, reserve it atomically,
enforce the remaining shared cap/concurrency, and deny unknown-price calls.
On timeout or unknown usage it must keep the reservation consumed: transport
failure does not prove the provider did not bill. These protocols provision no
credentials, make no price assumptions, and do not claim a vendor billing cap.
"""
from decimal import Decimal
from typing import Protocol


class SpendReservation(Protocol):
    async def settle(self, actual_cost_usd: Decimal | None) -> None: ...


class BudgetGuard(Protocol):
    async def reserve(self, *, operation: str, request_key: str, model: str) -> SpendReservation: ...
