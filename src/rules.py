"""
Two-layer voucher compliance review — Layer 1: Deterministic rule engine.

Runs 7 rules against each voucher and emits an Anomaly list per voucher.
Layer 2 (LLM judgment for edge cases) will live in llm_reviewer.py.

Design principles:
  - Rules must be explainable: every anomaly carries the rule_id and detail.
  - System-generated vouchers (depreciation, FX revaluation) are whitelisted.
  - Internal transfers (both sides on 100201) are whitelisted from doc/counterparty rules.
  - Thresholds live at the top of this file and are tuneable.

The bottom of this file also runs an evaluation: for each voucher whose data
was generated with an `_injected_anomaly` label, we check whether the expected
rule fired. This gives per-rule recall on the synthetic dataset, and is the
right kind of number to cite in a project write-up.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from decimal import Decimal
from typing import List, Optional
from collections import Counter

# Make Windows PowerShell print Chinese cleanly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from schema import Voucher, Anomaly


# ---------- Tuneable thresholds ----------

LARGE_AMOUNT_THRESHOLD = Decimal("30000.00")   # R003: manual entry risk cutoff
VAGUE_SUMMARY_AMOUNT   = Decimal("3000.00")    # R007: minimum amount to care about
VAGUE_SUMMARY_MAX_LEN  = 4                     # R007: summary ≤ this many chars = vague
MISSING_DOCS_AMOUNT    = Decimal("500.00")     # R002: tiny petty cash exempted


# ---------- Helpers ----------

def _is_internal_transfer(v: Voucher) -> bool:
    """Both sides on 100201 (bank deposit) → internal fund transfer."""
    return all(e.account_code == "100201" for e in v.entries)


def _has_expense_entry(v: Voucher) -> bool:
    """Any debit-side expense/cost entry (account starts with '5')?"""
    return any(e.debit_amount > 0 and e.account_code.startswith("5") for e in v.entries)


def _travel_entries(v: Voucher):
    """Yield (index, entry) for every 差旅 debit entry."""
    for i, e in enumerate(v.entries):
        if "差旅" in e.account_path and e.debit_amount > 0:
            yield i, e


# ---------- Rules ----------

def rule_001_balance(v: Voucher) -> List[Anomaly]:
    """R001 借贷不平衡 — data integrity, hard fail."""
    if v.is_balanced:
        return []
    return [Anomaly(
        voucher_id=v.voucher_id,
        rule_id="R001",
        severity="red",
        title="借贷不平衡",
        detail=f"借方合计 {v.total_debit}，贷方合计 {v.total_credit}，差额 {v.total_debit - v.total_credit}",
    )]


def rule_002_missing_docs(v: Voucher) -> List[Anomaly]:
    """R002 费用类支付无附单据 — reimbursement/payment without receipts."""
    if v.is_system_generated or _is_internal_transfer(v):
        return []
    if not _has_expense_entry(v):
        return []
    if v.attached_docs_count > 0:
        return []
    if v.total_amount < MISSING_DOCS_AMOUNT:
        return []
    return [Anomaly(
        voucher_id=v.voucher_id,
        rule_id="R002",
        severity="red",
        title="费用支付附单据数为 0",
        detail=f"金额 {v.total_amount}，非内部转账，非系统生成，但附单据数=0，缺少票据支撑",
    )]


def rule_003_manual_large(v: Voucher) -> List[Anomaly]:
    """R003 大额支付走总账 — bypassed 费控 pre-approval."""
    if v.is_system_generated or _is_internal_transfer(v):
        return []
    if v.source_system != "总账":
        return []
    if v.total_amount < LARGE_AMOUNT_THRESHOLD:
        return []
    return [Anomaly(
        voucher_id=v.voucher_id,
        rule_id="R003",
        severity="yellow",
        title="大额支付未经费控系统",
        detail=f"金额 {v.total_amount}，来源系统=「总账」（手动录入），未经费控服务预审",
    )]


def rule_004_travel_missing_personnel(v: Voucher) -> List[Anomaly]:
    """R004 差旅费缺【人员档案】— can't attribute reimbursement to a person."""
    if v.is_system_generated:
        return []
    out = []
    for i, e in _travel_entries(v):
        if e.tags.personnel is None:
            out.append(Anomaly(
                voucher_id=v.voucher_id,
                rule_id="R004",
                severity="yellow",
                title="差旅费缺少【人员档案】",
                detail=f"分录 {i+1}：{e.account_path}，金额 {e.debit_amount}，无【人员档案】tag，无法追责/归集",
            ))
    return out


def rule_005_travel_missing_project(v: Voucher) -> List[Anomaly]:
    """R005 差旅费缺【项目名称】— can't allocate to a project cost center."""
    if v.is_system_generated:
        return []
    out = []
    for i, e in _travel_entries(v):
        if e.tags.project_name is None:
            out.append(Anomaly(
                voucher_id=v.voucher_id,
                rule_id="R005",
                severity="yellow",
                title="差旅费缺少【项目名称】",
                detail=f"分录 {i+1}：{e.account_path}，金额 {e.debit_amount}，无【项目名称】tag，无法归入项目成本",
            ))
    return out


def rule_006_missing_counterparty(v: Voucher) -> List[Anomaly]:
    """R006 供应商付款缺【客商】— can't trace the transaction counterparty."""
    if v.is_system_generated or _is_internal_transfer(v):
        return []
    out = []
    for i, e in enumerate(v.entries):
        if e.debit_amount <= 0:
            continue
        if not e.account_code.startswith("500"):
            continue
        if "差旅" in e.account_path:
            continue  # covered by R004/R005
        if e.tags.counterparty is None and e.tags.personnel is None:
            out.append(Anomaly(
                voucher_id=v.voucher_id,
                rule_id="R006",
                severity="yellow",
                title="费用支出缺少【客商】",
                detail=f"分录 {i+1}：{e.account_path}，金额 {e.debit_amount}，无【客商】及【人员档案】，无法追溯交易对手",
            ))
    return out


def rule_007_vague_summary(v: Voucher) -> List[Anomaly]:
    """R007 大额付款配模糊摘要 — inadequate audit trail description."""
    if v.is_system_generated:
        return []
    if v.total_amount < VAGUE_SUMMARY_AMOUNT:
        return []
    out = []
    for i, e in enumerate(v.entries):
        if e.debit_amount <= 0:
            continue
        summary = e.summary.strip()
        if len(summary) <= VAGUE_SUMMARY_MAX_LEN:
            out.append(Anomaly(
                voucher_id=v.voucher_id,
                rule_id="R007",
                severity="yellow",
                title="大额支付摘要模糊",
                detail=f"分录 {i+1}：金额 {e.debit_amount}，摘要「{summary}」仅 {len(summary)} 字，缺少可审计的业务描述",
            ))
    return out


ALL_RULES = [
    rule_001_balance,
    rule_002_missing_docs,
    rule_003_manual_large,
    rule_004_travel_missing_personnel,
    rule_005_travel_missing_project,
    rule_006_missing_counterparty,
    rule_007_vague_summary,
]


def review_voucher(v: Voucher) -> List[Anomaly]:
    """Run all rules and return every anomaly triggered."""
    out: List[Anomaly] = []
    for rule in ALL_RULES:
        out.extend(rule(v))
    return out


# ---------- Loader ----------

def load_vouchers(path: Path):
    """Load JSON, return list of (Voucher, injected_label_or_None)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for item in raw:
        injected = item.pop("_injected_anomaly", None)
        v = Voucher.model_validate(item)
        result.append((v, injected))
    return result


# ---------- Evaluation ----------

LABEL_TO_RULE = {
    "A1_MISSING_DOCS_EXPENSE":     "R002",
    "A2_MANUAL_ENTRY_LARGE":       "R003",
    "A3_MISSING_PERSONNEL_TRAVEL": "R004",
    "A4_MISSING_PROJECT_TRAVEL":   "R005",
    "A5_MISSING_COUNTERPARTY":     "R006",
    "A6_VAGUE_SUMMARY_LARGE":      "R007",
}


def evaluate(pairs) -> None:
    """
    Per-rule TP/FN/FP against injected anomaly labels.

    Definitions used here:
      TP = voucher's expected rule fired
      FN = voucher's expected rule was silent (missed injection)
      FP = rule fired on a voucher whose injected label ≠ this rule's target
           (Some FPs are legitimate cross-detections, discussed in output.)
    """
    tp, fn, fp = Counter(), Counter(), Counter()

    for v, injected in pairs:
        flagged = {a.rule_id for a in review_voucher(v)}
        expected_rule = LABEL_TO_RULE.get(injected) if injected else None

        if expected_rule:
            if expected_rule in flagged:
                tp[expected_rule] += 1
            else:
                fn[expected_rule] += 1

        for rid in flagged:
            if rid == "R001":
                continue  # no injected counterpart
            if rid != expected_rule:
                fp[rid] += 1

    print("=" * 62)
    print(" Rule evaluation — synthetic dataset")
    print("=" * 62)
    print(f" {'Rule':<6}{'TP':>6}{'FN':>6}{'FP':>6}{'Recall':>10}")
    print("-" * 62)
    all_rules = sorted(set(tp) | set(fn) | set(fp))
    for rid in all_rules:
        t, f, p = tp[rid], fn[rid], fp[rid]
        expected = t + f
        recall = f"{t/expected*100:.1f}%" if expected else "  n/a"
        print(f" {rid:<6}{t:>6}{f:>6}{p:>6}{recall:>10}")
    print("-" * 62)
    print(" Note: some FPs are legitimate cross-detections. E.g. an A2 voucher")
    print(" (large + 总账) may also trigger R006 if counterparty is missing —")
    print(" both flags would be correct in a real audit.")


# ---------- Main ----------

def main():
    data_path = Path(__file__).parent.parent / "data" / "sample_vouchers.json"
    if not data_path.exists():
        print(f"ERROR: {data_path} not found. Run data_generator.py first.")
        return

    pairs = load_vouchers(data_path)
    print(f"Loaded {len(pairs)} vouchers from {data_path.name}\n")

    total = 0
    for v, injected in pairs:
        anomalies = review_voucher(v)
        if not anomalies:
            continue
        total += len(anomalies)
        label = f"  [injected: {injected}]" if injected else ""
        print(f"Voucher {v.voucher_id}  ({v.voucher_type}, {v.source_system}, ¥{v.total_amount}){label}")
        for a in anomalies:
            marker = {"red": "[RED]", "yellow": "[YEL]", "green": "[GRN]"}[a.severity]
            print(f"   {marker} [{a.rule_id}] {a.title}")
            print(f"          {a.detail}")
        print()

    print(f"\nTotal anomalies flagged: {total}\n")
    evaluate(pairs)


if __name__ == "__main__":
    main()
