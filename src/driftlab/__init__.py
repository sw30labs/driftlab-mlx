"""DriftLab — continuous compliance observer for running agentic systems.

DriftLab watches a live agent's actual decision traces and diffs observed
behavior against a certified OSCAL baseline. When behavior deviates it runs a
micro-experiment against a sandboxed replay to *prove* the drift with evidence.

The compliance path (diff, anomaly, scoring, experiment verdicts) is fully
deterministic and pure-Python. The LLM layer is optional and advisory-only.
"""

__version__ = "2.1.0"