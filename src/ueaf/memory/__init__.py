"""Governed memory domain (functional module 04).

Memory is never written directly by models; ``MemoryRecord`` is created only
from governed ``MemoryCandidate`` objects or authoritative sync, and sensitive
entries require consent.
"""
