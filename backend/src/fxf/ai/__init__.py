"""The experimental AI view: an LLM reads the same context the dashboard shows and gives,
per horizon, a probability that the rate rises, an expected change, a confidence and a
short reason.

It is held to the same bar as every other model, but it can only be scored live: an LLM
has seen historical exchange rates, so a backtest on past dates would be leakage. Each
daily forecast is stored as model "llm" before its outcome exists; fxf.ai.track scores
the ones whose target date has passed; the API lets it decide the "sell now?" verdict
only once 250 scored forecasts meet the promotion rule (fxf.api.signal).
"""
