# Calibration

Calibration should be done in layers.

1. Empty-board baseline: record all 64 Hall sensor values with no pieces.
2. Starting-position scan: record all normal starting pieces.
3. Runtime filtering: subtract baseline, oversample, classify occupancy and polarity.
4. Legal move reconciliation: python-chess remains the authority for move legality.

The sensor layer should report confidence and square changes. It should not be trusted as the sole source of chess legality.
