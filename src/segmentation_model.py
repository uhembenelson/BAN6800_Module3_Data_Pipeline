"""Starter configuration for four-persona customer segmentation."""

from __future__ import annotations

from sklearn.cluster import KMeans


def build_segmentation_model(random_state: int = 42) -> KMeans:
    """Create the planned four-cluster K-Means estimator."""
    return KMeans(n_clusters=4, n_init="auto", random_state=random_state)
