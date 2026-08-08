"""Provider-neutral contract for chaos fault lifecycle operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, NotRequired, TypedDict


class FaultInjectionResult(TypedDict):
    resource_kind: str
    resource_name: str
    namespace: str
    status: str
    injected_at: str
    resource_uid: NotRequired[str | None]


class FaultStatusResult(TypedDict):
    resource_kind: str
    resource_name: str
    namespace: str
    status: str


class BaseChaosAdapter(ABC):
    """Abstraction implemented by real and test chaos providers."""

    @abstractmethod
    def inject_fault(
        self,
        *,
        namespace: str,
        manifest: dict[str, Any],
    ) -> FaultInjectionResult:
        """Create a fault resource and return its durable identity."""

    @abstractmethod
    def get_fault_status(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
    ) -> FaultStatusResult:
        """Read the current provider status of a fault resource."""

    @abstractmethod
    def remove_fault(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
    ) -> None:
        """Request deletion of a fault resource (404 is idempotent)."""

    @abstractmethod
    def verify_cleanup(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        namespace: str,
        timeout_seconds: int = 30,
    ) -> bool:
        """Return whether the provider resource has been removed."""


# Short name retained for consumers that prefer ``ChaosAdapter``.
ChaosAdapter = BaseChaosAdapter