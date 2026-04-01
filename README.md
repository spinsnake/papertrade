# papertrade

Python scaffold for forward paper trading using platform-compatible contracts.

Current scope:
- domain contracts
- scheduler
- scoring engine
- rule evaluator
- portfolio simulator
- report filename rendering
- source adapter interfaces
- initial test suite

Not implemented yet:
- platform DB integration
- market bridge integration
- liquidation source
- full report persistence pipeline

run cli
python -m papertrade.cli run-forward