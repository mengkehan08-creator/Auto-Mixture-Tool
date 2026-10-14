from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class ComponentRegistry(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, component: T) -> None:
        component_id = getattr(component, "id")
        if component_id in self._items:
            raise ValueError(f"component already registered: {component_id}")
        self._items[component_id] = component

    def get(self, component_id: str) -> T:
        try:
            return self._items[component_id]
        except KeyError as exc:
            raise ValueError(f"unknown component: {component_id}") from exc

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"id": key, "name": getattr(value, "display_name")}
            for key, value in self._items.items()
        ]
