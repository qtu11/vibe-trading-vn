"""Resolve clickable attribution, including the inputs of derived values."""

from calendar import month_name

from src.reporting.schema import ResearchReport, Source


def apa_date(value) -> str:
    return f"{value.year}, {month_name[value.month]} {value.day}" if value else "n.d."


def reference_sources(sources: list[Source]) -> list[Source]:
    """One entry per URL, alphabetized by title (the recorded author is unknown)."""
    unique = {}
    for source in sources:
        unique.setdefault(str(source.url) if source.url else source.id, source)
    return sorted(unique.values(), key=lambda source: source.title.casefold())


def apa_reference_suffix(source: Source) -> str:
    # Publisher metadata is not an author byline: use APA's missing-author format.
    return f" ({apa_date(source.published_at)}). {source.provider}."


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
