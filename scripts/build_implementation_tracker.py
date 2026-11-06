"""Reconcile canonical requirements with explicit, bounded local delivery evidence."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ("CORE_AI_PLATFORM_67.md", "VIETNAM_STOCK_64.md", "FOREX_XAUUSD_62.md", "CRYPTO_72.md")
PATTERN = r"(?:PLATFORM|VN|FX|CRYPTO)-\d{3}"


def tracker_relative_links(text):
    """Catalog seams live in docs/specs; the tracker lives one level higher."""
    targets = re.findall(r"\]\(([^)]+)\)", text)
    assert all(target.startswith("../../") or target.startswith(("http://", "https://", "#"))
               for target in targets), f"Unexpected catalog link target: {text}"
    return text.replace("](../../", "](../")


def markdown_cell(text):
    return text.replace("|", "\\|")


def build():
    master = (ROOT / "VIBE_TRADING_MULTI_MARKET_MASTER_PLAN_V1.md").read_text(encoding="utf-8")
    canonical = re.findall(rf"^### ({PATTERN}) — (.+)$", master, re.MULTILINE)
    assert len(canonical) == 265 and len(dict(canonical)) == 265, "Canonical IDs missing or duplicated"
    progress = json.loads((ROOT / "docs/implementation_progress.json").read_text(encoding="utf-8"))
    baseline = {}
    for filename in CATALOGS:
        text = (ROOT / "docs/specs" / filename).read_text(encoding="utf-8")
        for line in text.splitlines():
            match = re.match(rf"^\| `({PATTERN})` \|", line)
            if not match:
                continue
            fields = [field.strip() for field in line.strip("| ").split(" | ")]
            assert len(fields) == 6, f"Invalid catalog row {match[1]}"
            spec_id, title, status, seam, acceptance, priority = fields
            spec_id = spec_id.strip("`")
            assert spec_id not in baseline, f"Duplicate catalog ID {spec_id}"
            baseline[spec_id] = dict(title=title, baseline_status=status.strip("`"),
                                     seam=seam, acceptance=acceptance, priority=priority)
    assert set(baseline) == set(dict(canonical)), "Catalog/master IDs differ"
    for delivery in progress["deliveries"]:
        assert delivery["status"] == "partial", "Whole-spec acceptance requires a separate complete evidence review"
        assert all(delivery.get(field) for field in ("key", "delivered", "remaining", "source", "tests")), \
            f"Incomplete delivery record: {delivery.get('key', '<missing key>')}"
        assert delivery["ids"] and set(delivery["ids"]) <= baseline.keys(), "Unknown delivery IDs"
        for relative in delivery["source"] + delivery["tests"]:
            assert (ROOT / relative).is_file(), f"Missing evidence file {relative}"
    requirements = []
    for spec_id, title in canonical:
        row = baseline[spec_id]
        assert title.strip() == row["title"], f"Title drift: {spec_id}"
        deliveries = [item for item in progress["deliveries"] if spec_id in item["ids"]]
        requirements.append(dict(id=spec_id, title=title.strip(), priority=row["priority"],
            baseline_status=row["baseline_status"], seam=row["seam"], acceptance_status="open",
            implementation_status="partial_delivered" if deliveries else "baseline_only",
            deliveries=[item["key"] for item in deliveries], remaining_acceptance=row["acceptance"]))
    counts = dict(Counter(item["implementation_status"] for item in requirements))
    baseline_counts = Counter(item["baseline_status"] for item in requirements)
    source_backed_statuses = ("source-partial", "PARTIAL", "source-existing", "EXISTING")
    proposed_statuses = ("proposed", "PROPOSED")
    source_backed = sum(baseline_counts[status] for status in source_backed_statuses)
    proposed = sum(baseline_counts[status] for status in proposed_statuses)
    domains = ("PLATFORM", "VN", "FX", "CRYPTO")
    domain_counts = {}
    for domain in domains:
        rows = [item for item in requirements if item["id"].startswith(f"{domain}-")]
        domain_counts[domain] = dict(
            total=len(rows),
            implementation=Counter(item["implementation_status"] for item in rows),
            baseline=Counter(item["baseline_status"] for item in rows),
        )
    priorities = ("P0", "P1", "P2")
    priority_counts = {}
    for priority in priorities:
        rows = [item for item in requirements if item["priority"] == priority]
        priority_counts[priority] = dict(
            total=len(rows),
            implementation=Counter(item["implementation_status"] for item in rows),
        )
    data = dict(schema_version=1, updated_at=progress["updated_at"], counts=counts,
                baseline_counts=dict(baseline_counts), priority_counts=priority_counts,
                seam_link_base="docs/specs",
                interpretation="baseline_only means not re-accepted here, not proof that no source implementation exists",
                deliveries=progress["deliveries"], requirements=requirements)
    lines = ["# Tiến độ triển khai theo 265 ID", "",
        f"Cập nhật: **{progress['updated_at']}**. Đối chiếu tự động với master và bốn catalog; tiêu đề/ID giữ nguyên.", "",
        "`partial_delivered`: đã nối một phần vào caller và có kiểm thử trong phạm vi ghi dưới đây. "
        "`baseline_only`: vẫn theo đánh giá source cũ, chưa nghiệm thu lại trong đợt này; không có nghĩa toàn bộ code chưa tồn tại. "
        "`acceptance_status: open` không được nâng thành hoàn tất vì một test hoặc một tool cùng tên.", "",
        f"**{counts.get('partial_delivered', 0)} ID có phần triển khai bổ sung; "
        f"{counts.get('baseline_only', 0)} ID còn ở baseline.** Không quy đổi thành phần trăm hoàn thành sản phẩm.", "",
        f"Theo baseline catalog: **{source_backed} ID có nền source** "
        f"(`source-partial` {baseline_counts['source-partial']}, `PARTIAL` {baseline_counts['PARTIAL']}, "
        f"`source-existing` {baseline_counts['source-existing']}, `EXISTING` {baseline_counts['EXISTING']}) và "
        f"**{proposed} ID `proposed`/`PROPOSED`**. Đây là trạng thái đánh giá source, không phải nghiệm thu.", "",
        "| Nhóm | ID | partial_delivered | baseline_only | Baseline có nền source | Baseline proposed |",
        "| --- | --- | --- | --- | --- | --- |"]
    for domain in domains:
        summary = domain_counts[domain]
        domain_source_backed = sum(summary["baseline"][status] for status in source_backed_statuses)
        domain_proposed = sum(summary["baseline"][status] for status in proposed_statuses)
        lines.append(f"| {domain} | {summary['total']} | {summary['implementation'].get('partial_delivered', 0)} | "
                     f"{summary['implementation'].get('baseline_only', 0)} | {domain_source_backed} | {domain_proposed} |")
    lines.extend(["", "| Ưu tiên | ID | partial_delivered | baseline_only |", "| --- | --- | --- | --- |"])
    for priority in priorities:
        summary = priority_counts[priority]
        lines.append(f"| {priority} | {summary['total']} | {summary['implementation'].get('partial_delivered', 0)} | "
                     f"{summary['implementation'].get('baseline_only', 0)} |")
    lines.extend(["",
        "Nguồn trạng thái: [implementation_progress.json](implementation_progress.json); "
        "bản máy đọc: [implementation_tracker.json](implementation_tracker.json). "
        "Tái tạo bằng `python scripts/build_implementation_tracker.py`; kiểm tra drift bằng `--check`.", "",
        "## Các phần đã bàn giao", ""])
    for item in progress["deliveries"]:
        lines.extend([f"### {item['key']}", "", item["delivered"], "",
            "IDs: " + ", ".join(f"`{spec_id}`" for spec_id in item["ids"]) + ".",
            "", "Còn thiếu: " + item["remaining"], "",
            "Source: " + ", ".join(f"[{Path(p).name}](../{p})" for p in item["source"]) + ".",
            "", "Tests: " + ", ".join(f"[{Path(p).name}](../{p})" for p in item["tests"]) + ".", ""])
    lines.extend(["## Danh mục 265 ID", "",
        "Baseline lấy nguyên từ catalog tương ứng; `partial_delivered` chỉ là phần nối thêm và không thay đổi acceptance. "
        "Cột gate giữ nguyên tiêu chí catalog, có thể gồm cả phần vừa được thực hiện; đọc cùng giới hạn ở delivery tương ứng. "
        "Link ở cột Source/seam đã đổi từ tương đối catalog (`docs/specs`) sang tương đối tracker (`docs`).", "",
        "| ID | Tên đặc tả | Ưu tiên | Baseline catalog | Source/seam hiện tại | Tiến độ bổ sung | Gate còn phải nghiệm thu đầy đủ |",
        "| --- | --- | --- | --- | --- | --- | --- |"])
    for item in requirements:
        lines.append(f"| `{item['id']}` | {markdown_cell(item['title'])} | {item['priority']} | "
                     f"{markdown_cell(item['baseline_status'])} | {markdown_cell(tracker_relative_links(item['seam']))} | "
                     f"{item['implementation_status']} | {markdown_cell(item['remaining_acceptance'])} |")
    return {"implementation_tracker.json": json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            "IMPLEMENTATION_TRACKER.md": "\n".join(lines) + "\n"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for filename, text in build().items():
        target = ROOT / "docs" / filename
        if args.check:
            assert target.read_text(encoding="utf-8") == text, f"Tracker drift: {filename}"
        else:
            target.write_text(text, encoding="utf-8")
    print("265 canonical requirements reconciled; acceptance remains explicit")
