"""Collect directly through Aside; no Chrome extension is required."""
from src.aside_collector import collect as collect_aside


def collect():
    return collect_aside()
