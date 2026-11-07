"""Resolve clickable attribution, including the inputs of derived values."""

from src.reporting.schema import ResearchReport


def datum_source_ids(report: ResearchReport | None, item) -> list[str]:
    if report is None:
        return list(dict.fromkeys(getattr(item, "source_ids", [])))
    metrics = {metric.key: metric for metric in [*report.financial_metrics, *report.valuation_metrics]}
    pending = [item]
    seen_inputs = set()
    ids = []
    while pending:
        current = pending.pop()
        ids.extend(getattr(current, "source_ids", []))
        for key in getattr(current, "input_keys", []):
            if key in metrics and key not in seen_inputs:
                seen_inputs.add(key)
                pending.append(metrics[key])
    sources = {source.id: source for source in report.sources}
    return [key for key in dict.fromkeys(ids) if key in sources]


def datum_sources(report: ResearchReport, item) -> list:
    sources = {source.id: source for source in report.sources}
    return [sources[key] for key in datum_source_ids(report, item) if sources[key].url]
