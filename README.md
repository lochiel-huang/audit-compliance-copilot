# Audit & Compliance Copilot

**AI-assisted anomaly detector for accounting vouchers**
An MVP that combines a deterministic rule engine with an LLM judgment layer to flag potentially non-compliant expense vouchers, keeping the accountant in the loop for final decisions.

## Problem
In small-to-mid-sized firms, accounts payable teams review vouchers manually — literally covering their desks with sticky notes to mark suspicious items. This is slow, inconsistent, and doesn't scale. Yet fully automating the review is risky: AI hallucination in a compliance context can cause real harm.

## Approach
Two-layer review:
1. **Rule engine (deterministic)** — handles the ~80% of clearly identifiable issues (missing supporting documents, missing required metadata tags, source-system risk classification, debit-credit imbalance).
2. **LLM judgment (probabilistic)** — provides second opinions on edge cases the rules can't confidently classify, with explicit reasoning.

Every flag returns: severity (red/yellow/green), rule/reasoning trail, and the specific fields involved. Nothing is auto-approved or auto-rejected — the human accountant remains the decision maker.

## Architecture
```
Voucher (JSON) → Rule Engine → Anomaly List
                     ↓
                LLM Reviewer (Claude API)
                     ↓
                Streamlit Dashboard
```

## Status
Under active development (Sprint 1 in progress). MVP target: end of July 2026.

## Key Design Principles
- **Human-in-the-loop**: The AI redistributes where human judgment goes, not replaces it.
- **Transparent reasoning**: Every flag includes the rule ID and/or LLM reasoning.
- **Whitelist for system-generated entries**: Auto-generated vouchers (depreciation, FX revaluation, month-end closing) bypass the compliance rules.
- **No real data**: All samples in this repo are synthetic. See `data/data_generator.py`.

## Stack
Python 3.11 · pandas · pydantic · Streamlit · Anthropic Claude API
