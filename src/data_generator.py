"""
Synthetic voucher generator.
Produces a mix of clean vouchers, system-generated vouchers, and vouchers
with realistic anomalies. Amounts, names, and dates are all fake.

Anomaly types injected:
  A1  MISSING_DOCS_EXPENSE       Reimbursement/expense with 附单据=0
  A2  MANUAL_ENTRY_LARGE         Large amount via 总账 (no 费控 pre-approval)
  A3  MISSING_PERSONNEL_TRAVEL   差旅费 without 人员档案 tag
  A4  MISSING_PROJECT_TRAVEL     差旅费 without 项目名称 tag
  A5  MISSING_COUNTERPARTY       供应商付款 without 客商 tag
  A6  VAGUE_SUMMARY_LARGE        Large amount with generic summary (<= 4 chars)
"""
from __future__ import annotations
import json
import random
from decimal import Decimal
from datetime import date, timedelta
from typing import List
from pathlib import Path

from schema import Voucher, VoucherEntry, VoucherTags


# ---------- Seed content ----------

FAKE_PERSONNEL = ["Clian", "Zeren", "Kesart", "Miran", "Lochi", "Adan", "Neris", "Faye"]
FAKE_DEPARTMENTS = ["行政部", "战略投资部", "财务部", "投资研究部", "合规部"]
FAKE_PROJECTS = ["Lenta", "Orion", "Kestrel", "Aster", "Vela", None]  # None = no project
FAKE_COUNTERPARTIES = [
    "易通行", "上海某某物业管理有限公司", "香港某某租赁", "某某差旅代理",
    "某某办公用品", "某某电讯", "某某保险", "某某会计师事务所",
]
FAKE_BANKS = ["某银行有限公司", "某某储蓄银行"]

BANK_ACCOUNT_MAIN = "某银行综合储蓄账户-HKD"
BANK_ACCOUNT_TRANSFER = "某银行往来账户-HKD"
CASH_FLOW_OPERATING = "支付其他与经营活动有关的现金"

# Common expense accounts
ACCOUNTS = {
    "car_expense":     ("500204", "行政费用\\行政费用-汽车费用"),
    "travel_domestic": ("500603", "业务费用\\业务费用-员工-差旅费（境内）"),
    "travel_overseas": ("500604", "业务费用\\业务费用-员工-差旅费（境外）"),
    "office_admin":    ("500201", "行政费用\\行政费用-办公费"),
    "utilities":       ("500202", "行政费用\\行政费用-水电费"),
    "rent":            ("500203", "行政费用\\行政费用-租金"),
    "entertainment":   ("500205", "行政费用\\行政费用-业务招待费"),
    "salary":          ("500101", "管理费用\\管理费用-工资"),
    "mpf":             ("500102", "管理费用\\管理费用-强积金"),
    "bank_deposit":    ("100201", "银行存款\\银行存款-活期"),
    "bank_charges":    ("500206", "行政费用\\行政费用-手续费"),
    "fx_gain_loss":    ("602001", "财务费用\\汇兑损益"),
    "depreciation":    ("500301", "管理费用\\累计折旧"),
    "prepaid_expense": ("122101", "预付账款\\预付账款-一般"),
}


# ---------- Helpers ----------

def _random_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))

def _round2(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))

def _make_bank_side(amount: Decimal, summary: str) -> VoucherEntry:
    """Credit side: money going out of the bank account."""
    code, path = ACCOUNTS["bank_deposit"]
    return VoucherEntry(
        summary=summary,
        account_code=code,
        account_path=path,
        tags=VoucherTags(
            cash_flow_item=CASH_FLOW_OPERATING,
            bank_file=random.choice(FAKE_BANKS),
            bank_account=BANK_ACCOUNT_MAIN,
        ),
        debit_amount=Decimal("0.00"),
        credit_amount=amount,
    )


# ---------- Clean voucher templates ----------

def clean_travel_voucher(vid: str, d: date) -> Voucher:
    person = random.choice(FAKE_PERSONNEL)
    project = random.choice([p for p in FAKE_PROJECTS if p])
    city = random.choice(["广州市", "深圳市", "上海市", "北京市"])
    amount = _round2(random.uniform(1500, 8500))
    code, path = ACCOUNTS["travel_domestic"]

    debit = VoucherEntry(
        summary=f"{person}, {city}, 差旅费",
        account_code=code,
        account_path=path,
        tags=VoucherTags(
            department="战略投资部",
            project_name=project,
            personnel=person,
        ),
        debit_amount=amount,
        credit_amount=Decimal("0.00"),
    )
    credit = _make_bank_side(amount, "差旅费")
    return Voucher(
        voucher_id=vid,
        voucher_type="银行凭证",
        voucher_date=d,
        source_system="费控服务",
        attached_docs_count=random.randint(2, 6),
        entries=[debit, credit],
        preparer=random.choice(FAKE_PERSONNEL),
        reviewer=random.choice(FAKE_PERSONNEL),
        bookkeeper=random.choice(FAKE_PERSONNEL),
    )


def clean_car_expense_voucher(vid: str, d: date) -> Voucher:
    counterparty = random.choice(["易通行", "某某加油站", "某某停车场"])
    amount = _round2(random.uniform(500, 3500))
    code, path = ACCOUNTS["car_expense"]

    debit = VoucherEntry(
        summary=f"{d.year}年{d.month}月{counterparty}",
        account_code=code,
        account_path=path,
        tags=VoucherTags(department="行政部", counterparty=counterparty),
        debit_amount=amount,
        credit_amount=Decimal("0.00"),
    )
    credit = _make_bank_side(amount, f"{d.year}年{d.month}月{counterparty}")
    return Voucher(
        voucher_id=vid,
        voucher_type="银行凭证",
        voucher_date=d,
        source_system="总账",
        attached_docs_count=random.randint(1, 5),
        entries=[debit, credit],
        preparer=random.choice(FAKE_PERSONNEL),
        reviewer=random.choice(FAKE_PERSONNEL),
        bookkeeper=random.choice(FAKE_PERSONNEL),
    )


def internal_transfer_voucher(vid: str, d: date) -> Voucher:
    """备付租金 style internal transfer between own bank accounts."""
    amount = _round2(random.uniform(50000, 200000))
    code, path = ACCOUNTS["bank_deposit"]

    debit = VoucherEntry(
        summary="备付租金-储蓄户转往来户",
        account_code=code,
        account_path=path,
        tags=VoucherTags(
            cash_flow_item=CASH_FLOW_OPERATING,
            bank_file=random.choice(FAKE_BANKS),
            bank_account=BANK_ACCOUNT_TRANSFER,
        ),
        debit_amount=amount,
        credit_amount=Decimal("0.00"),
    )
    credit = VoucherEntry(
        summary="储蓄户转往来户",
        account_code=code,
        account_path=path,
        tags=VoucherTags(
            cash_flow_item=CASH_FLOW_OPERATING,
            bank_file=random.choice(FAKE_BANKS),
            bank_account=BANK_ACCOUNT_MAIN,
        ),
        debit_amount=Decimal("0.00"),
        credit_amount=amount,
    )
    return Voucher(
        voucher_id=vid,
        voucher_type="银行凭证",
        voucher_date=d,
        source_system="总账",
        attached_docs_count=0,  # internal transfers legitimately have 0
        entries=[debit, credit],
        preparer=random.choice(FAKE_PERSONNEL),
        reviewer=random.choice(FAKE_PERSONNEL),
        bookkeeper=random.choice(FAKE_PERSONNEL),
    )


def system_depreciation_voucher(vid: str, d: date) -> Voucher:
    """Month-end auto-generated depreciation entry — should be whitelisted."""
    amount = _round2(random.uniform(3000, 12000))
    dep_code, dep_path = ACCOUNTS["depreciation"]
    exp_code, exp_path = ACCOUNTS["office_admin"]

    debit = VoucherEntry(
        summary="月末计提折旧",
        account_code=exp_code,
        account_path=exp_path,
        tags=VoucherTags(department="行政部"),
        debit_amount=amount,
        credit_amount=Decimal("0.00"),
    )
    credit = VoucherEntry(
        summary="月末计提折旧",
        account_code=dep_code,
        account_path=dep_path,
        tags=VoucherTags(),
        debit_amount=Decimal("0.00"),
        credit_amount=amount,
    )
    return Voucher(
        voucher_id=vid,
        voucher_type="记账凭证",
        voucher_date=d,
        source_system="总账",
        attached_docs_count=0,
        entries=[debit, credit],
        is_system_generated=True,
        preparer="SYSTEM",
        reviewer=random.choice(FAKE_PERSONNEL),
        bookkeeper=random.choice(FAKE_PERSONNEL),
    )


def clean_supplier_payment(vid: str, d: date) -> Voucher:
    counterparty = random.choice(FAKE_COUNTERPARTIES)
    amount = _round2(random.uniform(5000, 40000))
    code, path = ACCOUNTS["office_admin"]

    debit = VoucherEntry(
        summary=f"{counterparty}货款",
        account_code=code,
        account_path=path,
        tags=VoucherTags(department="行政部", counterparty=counterparty),
        debit_amount=amount,
        credit_amount=Decimal("0.00"),
    )
    credit = _make_bank_side(amount, f"{counterparty}货款")
    return Voucher(
        voucher_id=vid,
        voucher_type="银行凭证",
        voucher_date=d,
        source_system="费控服务",
        attached_docs_count=random.randint(2, 5),
        entries=[debit, credit],
        preparer=random.choice(FAKE_PERSONNEL),
        reviewer=random.choice(FAKE_PERSONNEL),
        bookkeeper=random.choice(FAKE_PERSONNEL),
    )


# ---------- Anomaly injectors ----------
# Each takes a clean voucher and mutates it into an anomalous one.

def inject_a1_missing_docs(v: Voucher) -> Voucher:
    """Expense reimbursement with 附单据=0."""
    v.attached_docs_count = 0
    return v

def inject_a2_manual_large(v: Voucher) -> Voucher:
    """Force 总账 entry with amount > 30000."""
    factor = Decimal("30000.00") / max(v.total_amount, Decimal("1"))
    if factor > 1:
        for e in v.entries:
            e.debit_amount = (e.debit_amount * factor).quantize(Decimal("0.01"))
            e.credit_amount = (e.credit_amount * factor).quantize(Decimal("0.01"))
    v.source_system = "总账"
    return v

def inject_a3_missing_personnel(v: Voucher) -> Voucher:
    """差旅费 without 人员档案 tag."""
    for e in v.entries:
        if "差旅" in e.account_path:
            e.tags.personnel = None
    return v

def inject_a4_missing_project(v: Voucher) -> Voucher:
    """差旅费 without 项目名称 tag."""
    for e in v.entries:
        if "差旅" in e.account_path:
            e.tags.project_name = None
    return v

def inject_a5_missing_counterparty(v: Voucher) -> Voucher:
    """Supplier payment without 客商 tag."""
    for e in v.entries:
        if e.debit_amount > 0:
            e.tags.counterparty = None
    return v

def inject_a6_vague_summary(v: Voucher) -> Voucher:
    """Large amount with vague summary."""
    for e in v.entries:
        e.summary = random.choice(["费用", "付款", "支出", "杂费"])
    return v


ANOMALY_INJECTORS = {
    "A1_MISSING_DOCS_EXPENSE":     inject_a1_missing_docs,
    "A2_MANUAL_ENTRY_LARGE":       inject_a2_manual_large,
    "A3_MISSING_PERSONNEL_TRAVEL": inject_a3_missing_personnel,
    "A4_MISSING_PROJECT_TRAVEL":   inject_a4_missing_project,
    "A5_MISSING_COUNTERPARTY":     inject_a5_missing_counterparty,
    "A6_VAGUE_SUMMARY_LARGE":      inject_a6_vague_summary,
}


# ---------- Main generator ----------

def generate_dataset(n: int = 30, seed: int = 42) -> List[dict]:
    """Generate n vouchers with a controlled mix of clean/anomalous samples."""
    random.seed(seed)
    start = date(2025, 6, 1)
    end   = date(2025, 8, 31)

    vouchers: List[dict] = []

    # We want roughly: 60% clean, 30% anomalous, 10% system-generated
    plan = (
        [("clean", None)] * int(n * 0.6)
        + [("system", None)] * int(n * 0.1)
        + [("anomalous", k) for k in list(ANOMALY_INJECTORS.keys()) * 20][: n - int(n * 0.6) - int(n * 0.1)]
    )
    random.shuffle(plan)

    for i, (kind, anomaly_key) in enumerate(plan, start=1):
        vid = f"{i:04d}"
        d = _random_date(start, end)

        if kind == "system":
            v = system_depreciation_voucher(vid, d)
        elif kind == "clean":
            v = random.choice([
                clean_travel_voucher,
                clean_car_expense_voucher,
                internal_transfer_voucher,
                clean_supplier_payment,
            ])(vid, d)
        else:  # anomalous
            # Match the anomaly to a suitable base voucher template
            if "TRAVEL" in anomaly_key:
                v = clean_travel_voucher(vid, d)
            elif anomaly_key == "A2_MANUAL_ENTRY_LARGE":
                v = clean_car_expense_voucher(vid, d)
            elif anomaly_key == "A5_MISSING_COUNTERPARTY":
                v = clean_supplier_payment(vid, d)
            else:  # A1, A6
                v = clean_supplier_payment(vid, d)
            v = ANOMALY_INJECTORS[anomaly_key](v)

        # Serialize with the injected anomaly label for later evaluation
        d_out = json.loads(v.model_dump_json())
        d_out["_injected_anomaly"] = anomaly_key  # None if clean/system
        vouchers.append(d_out)

    return vouchers


def main():
    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    dataset = generate_dataset(n=100, seed=42)
    out_path = out_dir / "sample_vouchers.json"
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Summary
    from collections import Counter
    labels = Counter(v.get("_injected_anomaly") or "CLEAN_OR_SYSTEM" for v in dataset)
    print(f"Generated {len(dataset)} vouchers → {out_path}")
    for label, count in sorted(labels.items()):
        print(f"  {label}: {count}")


if __name__ == "__main__":
    main()
