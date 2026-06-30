"""Back-compat shim — moved to `benchmark.smallgap.interp.generate` (smallgap pipeline-stage split 2026-06-25).
Transparent re-export so .scratch box drivers + the box mirror keep the old path.
"""
import sys as _sys
import benchmark.smallgap.interp.generate as _m
_sys.modules[__name__] = _m
if __name__ == "__main__" and hasattr(_m, "main"):
    raise SystemExit(_m.main())
