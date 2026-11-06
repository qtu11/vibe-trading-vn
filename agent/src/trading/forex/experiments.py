"""Actual local evaluator identity, separate from caller-declared dataset revisions."""

import hashlib
import platform
from importlib.metadata import version
from pathlib import Path

from src.quantlib import crossvalidation
from . import research_dataset, research_signals, runner, walk_forward


def engine_manifest(*, experiment_kind: str | None = None) -> dict:
    modules = (walk_forward, research_dataset, runner, research_signals, crossvalidation)
    if experiment_kind == "frozen_oos_cost_stress":
        from . import cost_stress

        modules += (cost_stress,)
    elif experiment_kind == "frozen_oos_moving_block_bootstrap":
        from src.quantlib import risk
        from . import trade_paths

        modules += (trade_paths, risk)
    elif experiment_kind == "causal_atr_sma_regime":
        from src.shadow_account import indicators
        from . import regime, research_indicators

        modules += (regime, research_indicators, indicators)
    elif experiment_kind is not None:
        raise ValueError("Unsupported research experiment kind")
    sources = {}
    for module in modules:
        try:
            sources[module.__name__] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        except OSError:
            sources[module.__name__] = None
    manifest = {
        "registry_version": 1,
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("numpy", "pydantic")},
        "source_sha256": sources,
        "source_verification": "local_installed_source_hashes",
    }
    if experiment_kind is not None:
        manifest["experiment_kind"] = experiment_kind
    return manifest
