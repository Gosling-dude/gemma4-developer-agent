"""Local, offline re-implementation of the competition harness (`swegemma`).

This is not the official harness. It re-implements the documented contract (HARNESS_README) closely
enough to run and measure agents locally: the 9 tools with the same signatures, JSON shapes, truncation
limits and budget gates, patch extraction, and Phase-2 verification. Known differences are listed in
docs/architecture.md ("Local harness fidelity").
"""
