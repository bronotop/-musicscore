"""Choose a grand-staff split pitch for piano parts.

Fixed middle C is a good default, but piano writing sometimes sits clearly in
two registers (e.g., a low accompaniment and a high melody). A conservative
2-means split can follow that layout without moving notes across hands when the
distribution is not clearly bimodal.
"""

from __future__ import annotations

import numpy as np

DEFAULT_SPLIT = 60
MIN_NOTES = 24
MIN_SEPARATION = 7
MIN_CLUSTER_GAP = 5
MIN_SIDE_SHARE = 0.10


def choose_split_pitch(
    pitches: list[int] | np.ndarray,
    default: int = DEFAULT_SPLIT,
) -> int:
    """Return a split pitch: notes >= split go to the right hand."""
    values = np.asarray(sorted(int(pitch) for pitch in pitches), dtype=float)
    if values.size < MIN_NOTES:
        return default

    low = float(np.percentile(values, 25))
    high = float(np.percentile(values, 75))
    centers = np.array([low, high], dtype=float)
    labels = np.zeros(values.size, dtype=int)

    for _ in range(24):
        distances = np.abs(values[:, None] - centers[None, :])
        labels = distances.argmin(axis=1)
        if not (labels == 0).any() or not (labels == 1).any():
            return default
        updated = np.array(
            [values[labels == 0].mean(), values[labels == 1].mean()]
        )
        if np.allclose(updated, centers, atol=0.05):
            centers = updated
            break
        centers = updated

    low_values = values[labels == 0]
    high_values = values[labels == 1]
    if high_values.min() - low_values.max() < MIN_CLUSTER_GAP:
        return default
    if abs(high_values.mean() - low_values.mean()) < MIN_SEPARATION:
        return default
    if (values < (low_values.mean() + high_values.mean()) / 2).mean() < MIN_SIDE_SHARE:
        return default

    split = int(round((low_values.mean() + high_values.mean()) / 2))
    return max(48, min(72, split))
