# Notes on real voucher structure

Observations distilled from three real bank vouchers (with all identifying info redacted).

## Voucher-level fields
| Field | Values seen | Compliance signal |
|---|---|---|
| 凭证类型 | 银行凭证, 记账凭证 | 银行凭证 = cash movement; 记账凭证 = adjustment |
| 来源系统 | 总账, 费控服务 | **总账 = manual entry, higher risk. 费控服务 = pre-approved via expense system.** |
| 附单据 | 0, 4, ... | 0 legitimate for internal transfers and system-generated. Otherwise a red flag for expense reimbursement. |
| 制单 / 审核 / 出纳 / 记账 | Four signature slots | Segregation of duties. Preparer ≠ Reviewer should be enforced. |

## Line-level fields
| Field | Notes |
|---|---|
| 摘要 | Free text. Real cases include short ("差旅费") and detailed ("Clian, 广州市, 差旅费"). Overly short summaries on large amounts are suspicious. |
| 会计科目 | Structured: 编码 + path + tags. Tags are `【key：value】` inline. |
| 借方本币 / 贷方本币 | An entry is either debit or credit, never both. A voucher can have multiple lines each side. Total debit must equal total credit. |

## Common tag semantics
- **【部门】** required for most expense entries
- **【客商】** required for supplier payments and specific service providers (e.g. 汽车费用-易通行)
- **【项目名称】** required for costs allocated to specific projects (e.g. investment analysis for a target)
- **【人员档案】** required for reimbursements traceable to an individual (差旅费, 报销)
- **【现金流量项目】** required for bank account entries (100201) — needed for cash flow statement classification
- **【银行档案】** + **【银行账户】** required for any bank deposit entry

## System-generated vouchers (whitelist candidates)
- 月末计提折旧 (monthly depreciation)
- 长期待摊费用摊销 (amortization)
- 月末汇兑损益结转 (FX revaluation)
- 月末损益结转 (P&L closing entries)

These come with 制单=SYSTEM or similar marker in real systems and should bypass most anomaly rules.
