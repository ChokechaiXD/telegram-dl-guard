"""Hash cache — LRU with bounded size."""
from __future__ import annotations


class HashCache:
    """Thread-safe LRU cache for file hashes.

    Tracks hash -> filepath mappings with automatic eviction.
    Used by upload_tracker and dedup.
    """

    def __init__(self, max_size: int = 2048):
        self._max = max_size
        self._cache: dict[str, str] = {}  # hash -> filepath
        self._order: list[str] = []  # MRU at end

    def put(self, file_hash: str, filepath: str) -> None:
        if file_hash in self._cache:
            # Move to MRU
            self._order.remove(file_hash)
        elif len(self._order) >= self._max:
            # Evict LRU
            evicted = self._order.pop(0)
            del self._cache[evicted]
        self._cache[file_hash] = filepath
        self._order.append(file_hash)

    def get(self, file_hash: str) -> str | None:
        return self._cache.get(file_hash)

    def __contains__(self, file_hash: str) -> bool:
        return file_hash in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()
