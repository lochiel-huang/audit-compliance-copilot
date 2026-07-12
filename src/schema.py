"""
Pydantic models for accounting vouchers.
Structure mirrors real 记账凭证/银行凭证 from Yonyou (用友) NC/U8 systems.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Optional, List, Literal
from datetime import date
from pydantic import BaseModel, Field, model_validator


class VoucherTags(BaseModel):
    """
    Structured metadata attached to 会计科目.
    In real vouchers these appear as 【部门：X】【客商：Y】etc.
    """
    department: Optional[str] = Field(None, description="部门")
    counterparty: Optional[str] = Field(None, description="客商")
    project_name: Optional[str] = Field(None, description="项目名称")
    personnel: Optional[str] = Field(None, description="人员档案")
    cash_flow_item: Optional[str] = Field(None, description="现金流量项目")
    bank_file: Optional[str] = Field(None, description="银行档案")
    bank_account: Optional[str] = Field(None, description="银行账户")

    def to_display_string(self) -> str:
        """Render tags back into the 【key：value】 format for display."""
        parts = []
        mapping = {
            "department": "部门",
            "counterparty": "客商",
            "project_name": "项目名称",
            "personnel": "人员档案",
            "cash_flow_item": "现金流量项目",
            "bank_file": "银行档案",
            "bank_account": "银行账户",
        }
        for field, label in mapping.items():
            val = getattr(self, field)
            if val:
                parts.append(f"【{label}：{val}】")
        return "".join(parts)


class VoucherEntry(BaseModel):
    """
    One line in a voucher — either a debit or a credit entry.
    A voucher can have multiple entries (2+ lines is common).
    """
    summary: str = Field(..., description="摘要")
    account_code: str = Field(..., description="会计科目编码, e.g. '500204'")
    account_path: str = Field(..., description="会计科目路径, e.g. '行政费用\\\\行政费用-汽车费用'")
    tags: VoucherTags = Field(default_factory=VoucherTags)
    debit_amount: Decimal = Field(Decimal("0.00"), description="借方本币")
    credit_amount: Decimal = Field(Decimal("0.00"), description="贷方本币")

    @model_validator(mode="after")
    def check_debit_xor_credit(self) -> "VoucherEntry":
        """One entry is either debit or credit — not both, not neither."""
        d = self.debit_amount
        c = self.credit_amount
        if (d > 0 and c > 0) or (d == 0 and c == 0):
            raise ValueError(
                f"Entry must have exactly one non-zero side. Got debit={d}, credit={c}"
            )
        return self


class Voucher(BaseModel):
    """A complete accounting voucher (记账凭证 or 银行凭证)."""
    voucher_id: str = Field(..., description="凭证号, e.g. '0033'")
    voucher_type: Literal["银行凭证", "记账凭证"] = "银行凭证"
    voucher_date: date = Field(..., description="制单日期")
    book: str = Field("HK Book", description="账套")
    source_system: Literal["总账", "费控服务"] = Field("总账", description="来源系统")
    attached_docs_count: int = Field(0, description="附单据数量")
    entries: List[VoucherEntry] = Field(..., min_length=2)

    # Signatures — real vouchers have four
    preparer: Optional[str] = Field(None, description="制单")
    reviewer: Optional[str] = Field(None, description="审核")
    cashier: Optional[str] = Field(None, description="出纳")
    bookkeeper: Optional[str] = Field(None, description="记账")

    # Marks this as a system-auto-generated voucher (e.g. depreciation, FX revaluation)
    # These should be whitelisted from most compliance rules.
    is_system_generated: bool = Field(False, description="是否为系统自动生成 (折旧/摊销/汇兑损益/月末结转)")

    @property
    def total_debit(self) -> Decimal:
        return sum((e.debit_amount for e in self.entries), Decimal("0.00"))

    @property
    def total_credit(self) -> Decimal:
        return sum((e.credit_amount for e in self.entries), Decimal("0.00"))

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def total_amount(self) -> Decimal:
        """Return the voucher's principal amount (either side, since balanced)."""
        return max(self.total_debit, self.total_credit)


# ---------- Anomaly output schema ----------

Severity = Literal["red", "yellow", "green"]


class Anomaly(BaseModel):
    """A single flag raised against a voucher."""
    voucher_id: str
    rule_id: str = Field(..., description="e.g. 'R001', or 'LLM' for LLM-only flags")
    severity: Severity
    title: str = Field(..., description="Short human-readable title")
    detail: str = Field(..., description="Reasoning: which field, what value, why suspicious")
    source: Literal["rule", "llm"] = "rule"
