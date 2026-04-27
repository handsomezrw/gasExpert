"""Topology cache — LRU + TTL for external topology / valve data.

避免每次调 skill 都远程拉拓扑 → 降低延迟、提高容错。
Phase 7 接入真实 Web 地图时启用，当前 mock server 延迟低，缓存不是必须的，
但接口已经定义好，真实切换只需改调用的 cache_key。
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Callable


class TopologyCache:
    """Simple in-memory LRU cache with TTL expiry.

    Usage::

        cache = TopologyCache(maxsize=32, ttl_seconds=300)
        data = cache.get_or_fetch("subgraph:center=...", fetcher)
    """

    def __init__(self, maxsize: int = 32, ttl_seconds: int = 300) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def _is_expired(self, entry: tuple[float, Any]) -> bool:
        return time.monotonic() - entry[0] > self._ttl

    def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        ts, value = self._store[key]
        if self._is_expired((ts, value)):
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        while len(self._store) >= self._maxsize:
            self._store.popitem(last=False)
        self._store[key] = (time.monotonic(), value)

    def get_or_fetch(self, key: str, fetcher: Callable[[], Any]) -> Any:
        existing = self.get(key)
        if existing is not None:
            return existing
        value = fetcher()
        self.set(key, value)
        return value

    def invalidate(self, key_prefix: str) -> int:
        """Invalidate all keys starting with *key_prefix*. Returns count."""
        keys = [k for k in self._store if k.startswith(key_prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def keys(self) -> list[str]:
        return list(self._store.keys())


# Singleton — imported by skills and agent nodes
topo_cache = TopologyCache(maxsize=32, ttl_seconds=300)
