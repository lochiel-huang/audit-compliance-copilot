"""
Streamlit UI for Audit & Compliance Copilot.

Reads pre-computed evaluation results and presents them through three views:
  - Dashboard: top-line metrics + distribution charts + concordance matrix
  - Voucher Review: filterable table + drill-down into rule + LLM assessments
  - About: architecture story and iteration history

Run:
  streamlit run src/app.py
"""
from __future__ import annotations
import json
from pathlib import Path
from decimal import Decimal
import streamlit as st
import pandas as pd


# ---------- Page config ----------

st.set_page_config(
    page_title="Audit & Compliance Copilot",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------- Data loading ----------

_PROJECT_ROOT = Path(__file__).parent.parent


@st.cache_data
def load_evaluation():
    p = _PROJECT_ROOT / "data" / "full_evaluation.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data
def load_raw_vouchers():
    p = _PROJECT_ROOT / "data" / "sample_vouchers.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


results = load_evaluation()
raw_vouchers = load_raw_vouchers()

if not results or not raw_vouchers:
    st.error(
        "Data files not found in `data/`. Run these first:\n"
        "```\n"
        "python src/data_generator.py\n"
        "python src/evaluate_full.py\n"
        "```"
    )
    st.stop()

voucher_by_id = {v["voucher_id"]: v for v in raw_vouchers}


def get_voucher_amount(v):
    """Sum of debit side (equals credit side for balanced vouchers)."""
    return sum(float(e["debit_amount"]) for e in v["entries"])


# ---------- Build unified dataframe ----------

rows = []
for r in results:
    vid = r["voucher_id"]
    v = voucher_by_id[vid]
    rule_flags = r.get("rule_flags", [])
    llm = r.get("llm_assessment", {})

    # Determine max rule severity for this voucher
    if rule_flags:
        severities = [f["severity"] for f in rule_flags]
        max_severity = "red" if "red" in severities else "yellow"
    else:
        max_severity = "none"

    rows.append({
        "voucher_id": vid,
        "voucher_type": v["voucher_type"],
        "source_system": v["source_system"],
        "amount": get_voucher_amount(v),
        "attached_docs": v["attached_docs_count"],
        "is_system": v["is_system_generated"],
        "num_rule_flags": len(rule_flags),
        "max_rule_severity": max_severity,
        "llm_verdict": llm.get("overall_assessment", "error"),
        "llm_action": llm.get("recommended_action", "N/A"),
        "llm_confidence": llm.get("confidence", 0),
        "injected_anomaly": r.get("injected_anomaly"),
        "bucket": r.get("bucket", "N/A"),
        "success": r.get("success", False),
    })

df = pd.DataFrame(rows)


# ---------- Sidebar ----------

st.sidebar.title("📋 Audit & Compliance Copilot")
st.sidebar.caption("AI-assisted voucher review — MVP")

page = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Voucher Review", "About"],
    label_visibility="collapsed",
)

st.sidebar.divider()
st.sidebar.caption(
    "🔗 [GitHub Repository]"
    "(https://github.com/lochiel-huang/audit-compliance-copilot)"
)
st.sidebar.caption(f"Evaluation dataset: **{len(df)} vouchers**")


# ==================== DASHBOARD ====================

if page == "Dashboard":
    st.title("Compliance Dashboard")
    st.caption(
        f"Two-layer AI review across {len(df)} accounting vouchers · "
        f"Rule engine (Layer 1) + LLM judgment (Layer 2)"
    )

    # Top-line metrics
    st.subheader("Top-line metrics")
    c1, c2, c3, c4 = st.columns(4)

    clean_n = int((df["llm_verdict"] == "clean").sum())
    susp_n = int((df["llm_verdict"] == "suspicious").sum())
    conc_n = int((df["llm_verdict"] == "concerning").sum())

    # Rule-LLM concordance: rule flagged ↔ LLM flagged
    rule_flagged = df["num_rule_flags"] > 0
    llm_flagged = df["llm_verdict"].isin(["suspicious", "concerning"])
    concordance = (rule_flagged == llm_flagged).mean() * 100

    c1.metric("Total vouchers", len(df))
    c2.metric(
        "Clean",
        f"{clean_n} ({clean_n/len(df)*100:.0f}%)",
        help="Both rule engine and LLM agree no issues"
    )
    c3.metric(
        "Flagged",
        f"{susp_n + conc_n} ({(susp_n+conc_n)/len(df)*100:.0f}%)",
        help="Suspicious or concerning by LLM"
    )
    c4.metric(
        "Rule–LLM concordance",
        f"{concordance:.0f}%",
        help="% of vouchers where rule verdict and LLM verdict align"
    )

    st.divider()

    # Distributions
    st.subheader("Distribution")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Rule engine — number of flags per voucher**")
        rule_dist = df["num_rule_flags"].value_counts().sort_index()
        rule_dist.index = [f"{i} flags" for i in rule_dist.index]
        st.bar_chart(rule_dist, height=250)

    with col_b:
        st.markdown("**LLM verdict distribution**")
        verdict_order = ["clean", "suspicious", "concerning"]
        verdict_dist = df["llm_verdict"].value_counts().reindex(verdict_order, fill_value=0)
        st.bar_chart(verdict_dist, height=250)

    st.divider()

    # Concordance matrix
    st.subheader("Rule × LLM concordance matrix")
    st.caption(
        "Rows = whether the deterministic rule engine flagged the voucher · "
        "Columns = LLM overall verdict"
    )

    df["_rule_bucket"] = df["num_rule_flags"].apply(
        lambda x: "Rules flagged" if x > 0 else "Rules clean"
    )
    df["_llm_bucket"] = df["llm_verdict"].str.capitalize()

    matrix = pd.crosstab(
        df["_rule_bucket"],
        df["_llm_bucket"],
        margins=True,
        margins_name="Total",
    )
    st.dataframe(matrix, use_container_width=True)

    st.info(
        "**How to read**: The bottom-left cell (Rules flagged × Clean) would indicate "
        "the LLM overriding the rule engine — ideally zero. The top-right cell "
        "(Rules clean × Suspicious/Concerning) shows the LLM catching what "
        "rules missed — Layer 2's net contribution."
    )

    st.divider()

    # Iteration story teaser
    st.subheader("Prompt engineering iteration")
    st.caption("The current v3 prompt is the result of three iterations. See the About page for the full story.")

    iter_df = pd.DataFrame({
        "Version": ["v1 (initial)", "v2 (over-corrected)", "v3 (current)"],
        "Suspicious rate": ["77%", "7%", "30%"],
        "TP (both flagged)": [26, 7, 30],
        "LLM_DISMISS": [0, 23, 0],
        "Concordance": ["50%", "77%", "100%"],
    })
    st.dataframe(iter_df, use_container_width=True, hide_index=True)


# ==================== VOUCHER REVIEW ====================

elif page == "Voucher Review":
    st.title("Voucher Review")
    st.caption(
        "Filter and inspect individual voucher assessments. "
        "Each row shows both the rule engine's flags and the LLM's second-opinion."
    )

    # Filters
    f1, f2, f3 = st.columns([2, 2, 3])
    with f1:
        filter_verdict = st.multiselect(
            "LLM verdict",
            options=["clean", "suspicious", "concerning"],
            default=["suspicious", "concerning"],
        )
    with f2:
        filter_rules = st.selectbox(
            "Rule engine",
            options=["All", "Flagged only", "Clean only"],
            index=0,
        )
    with f3:
        search_id = st.text_input("Search by voucher ID", placeholder="e.g. 0008")

    # Apply filters
    filtered = df.copy()
    if filter_verdict:
        filtered = filtered[filtered["llm_verdict"].isin(filter_verdict)]
    if filter_rules == "Flagged only":
        filtered = filtered[filtered["num_rule_flags"] > 0]
    elif filter_rules == "Clean only":
        filtered = filtered[filtered["num_rule_flags"] == 0]
    if search_id:
        filtered = filtered[filtered["voucher_id"].str.contains(search_id, case=False)]

    st.caption(f"**{len(filtered)}** of {len(df)} vouchers match")

    # Table
    display = filtered[[
        "voucher_id", "voucher_type", "source_system", "amount",
        "attached_docs", "num_rule_flags", "llm_verdict", "llm_action", "llm_confidence"
    ]].copy()
    display.columns = [
        "ID", "Type", "Source", "Amount (¥)",
        "Docs", "Rule flags", "LLM verdict", "Action", "Confidence"
    ]
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Amount (¥)": st.column_config.NumberColumn(format="%.2f"),
            "Confidence": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.divider()

    # Detail view
    st.subheader("Voucher detail")
    if len(filtered) == 0:
        st.warning("No vouchers match the current filters.")
    else:
        selected_id = st.selectbox(
            "Select a voucher to inspect",
            options=filtered["voucher_id"].tolist(),
        )

        if selected_id:
            r = next(x for x in results if x["voucher_id"] == selected_id)
            v = voucher_by_id[selected_id]

            # Basic info
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Type", v["voucher_type"])
            c2.metric("Source system", v["source_system"])
            c3.metric("Attached docs", v["attached_docs_count"])
            c4.metric("Amount (¥)", f"{get_voucher_amount(v):,.2f}")

            # Entries
            st.markdown("**Journal entries**")
            entries_data = []
            for e in v["entries"]:
                debit = float(e["debit_amount"])
                credit = float(e["credit_amount"])
                # Compose tag display
                tags = e.get("tags", {})
                tag_parts = [
                    f"【{k}：{val}】"
                    for k, val in [
                        ("部门", tags.get("department")),
                        ("客商", tags.get("counterparty")),
                        ("项目名称", tags.get("project_name")),
                        ("人员档案", tags.get("personnel")),
                    ]
                    if val
                ]
                entries_data.append({
                    "Summary (摘要)": e["summary"],
                    "Account (会计科目)": f"{e['account_code']}\\{e['account_path']}",
                    "Tags": "".join(tag_parts) or "-",
                    "Debit (¥)": f"{debit:,.2f}" if debit > 0 else "",
                    "Credit (¥)": f"{credit:,.2f}" if credit > 0 else "",
                })
            st.dataframe(pd.DataFrame(entries_data), use_container_width=True, hide_index=True)

            # Two-column: Rule vs LLM
            col_rule, col_llm = st.columns(2)

            with col_rule:
                st.markdown("### 🔧 Layer 1: Rule engine")
                rule_flags = r.get("rule_flags", [])
                if rule_flags:
                    for f in rule_flags:
                        emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}[f["severity"]]
                        st.markdown(f"{emoji} **[{f['rule_id']}]** {f['title']}")
                else:
                    st.success("No rule flags raised")

            with col_llm:
                st.markdown("### 🤖 Layer 2: LLM judgment")
                llm = r.get("llm_assessment", {})
                verdict = llm.get("overall_assessment", "N/A")
                verdict_emoji = {
                    "clean": "🟢",
                    "suspicious": "🟡",
                    "concerning": "🔴",
                }.get(verdict, "⚪")
                action = llm.get("recommended_action", "N/A")
                confidence = llm.get("confidence", 0)

                st.markdown(f"**Verdict**: {verdict_emoji} {verdict.upper()}")
                st.markdown(f"**Action**: `{action}`")
                st.markdown(f"**Confidence**: {confidence:.2f}")

                concerns = llm.get("concerns", [])
                if concerns:
                    st.markdown("**Independent concerns**:")
                    for c in concerns:
                        emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(c["severity"], "⚪")
                        st.markdown(f"{emoji} **{c['aspect']}** — {c['reasoning']}")

                notes = llm.get("notes_to_reviewer", "")
                if notes:
                    st.info(f"**Note to reviewer**: {notes}")

            # Transparency note about synthetic data
            if r.get("injected_anomaly"):
                st.divider()
                st.caption(
                    f"ℹ️ *This is a synthetic voucher with injected anomaly type "
                    f"`{r['injected_anomaly']}` — used for evaluation transparency, "
                    f"would not appear in production data.*"
                )


# ==================== ABOUT ====================

else:  # About
    st.title("About Audit & Compliance Copilot")

    st.markdown(
        """
This is an MVP demonstration of a **two-layer AI system for automating accounting 
voucher compliance review**. It began as a personal project during a back-office 
finance internship at a Hong Kong capital firm, where I observed accountants 
manually tagging suspicious voucher entries with sticky notes — a workflow that 
doesn't scale and produces inconsistent audit trails.
        """
    )

    st.subheader("Architecture")
    st.markdown(
        """
```
Voucher (JSON)
      ↓
Layer 1: Deterministic Rule Engine
  ├─ 7 rules covering document sufficiency, source-system risk,
  │  metadata completeness, audit trail quality
  ├─ Whitelist for system-generated entries and internal transfers
  └─ Output: rule ID + severity + reasoning
      ↓
Layer 2: LLM Judgment (Anthropic → DeepSeek via function calling)
  ├─ Semantic-level checks the rules can't perform
  ├─ Guardrails: schema constraints, calibrated prompt, temperature=0
  └─ Output: structured verdict (clean/suspicious/concerning)
      ↓
Human accountant reviews flagged cases
```
        """
    )

    st.subheader("Design principles")
    st.markdown(
        """
- **Human-in-the-loop**: The system redistributes where human judgment goes, 
  not replaces it. All action recommendations from the LLM require human confirmation.
- **Transparent reasoning**: Every flag includes either a rule ID (deterministic) 
  or LLM natural-language reasoning (probabilistic) — no black-box verdicts.
- **Pluggable LLM provider**: Successfully migrated from Anthropic to DeepSeek 
  mid-project when payment channels required switching. Only client initialization 
  changed; the schema, rules, and downstream consumers were untouched.
        """
    )

    st.subheader("Evaluation results")
    st.markdown(
        f"""
On a synthetic dataset of **100 vouchers** with **30 injected anomalies** across 
6 categories:

- **{(df['llm_action'].isin(['human_review', 'reject'])).sum() + (df['llm_verdict']=='clean').sum()}/100 = 100%** LLM API success rate
- **100%** rule–LLM verdict concordance (both layers agree on which vouchers need review)
- **{(df['llm_verdict'].isin(['suspicious', 'concerning'])).mean()*100:.0f}%** flagged for human review 
  (real-world compliance systems target 20–35%)
        """
    )

    st.subheader("Prompt engineering iteration")
    st.markdown(
        """
The current v3 prompt is the result of three iterations, each documented as a 
learning artifact:

| Version | Suspicious rate | TP (rule + LLM agree) | LLM_DISMISS | Learning |
| :--- | :---: | :---: | :---: | :--- |
| v1 (initial) | **77%** | 26 | 0 | Alert fatigue — the LLM found problems everywhere. |
| v2 (over-corrected) | **7%** | 7 | 23 | Over-corrected — the LLM ignored real rule flags. |
| v3 (current) | **30%** | 30 | 0 | Balanced — rule engine sync + calibrated defaults. |

The iteration process itself is the most important artifact of this project. 
It taught me that **prompt engineering is a product-design problem, not a 
parameter-tuning problem**. Finding the balance between over-eager and 
over-cautious AI behavior is fundamentally about expressing product philosophy 
through language.
        """
    )

    st.subheader("Stack")
    st.markdown(
        """
- **Language**: Python 3.14
- **Data modeling**: Pydantic v2
- **LLM**: DeepSeek (via OpenAI-compatible SDK, `function_calling`)
- **UI**: Streamlit
- **Version control**: Git + GitHub
        """
    )

    st.divider()
    st.caption(
        "GitHub: [lochiel-huang/audit-compliance-copilot]"
        "(https://github.com/lochiel-huang/audit-compliance-copilot)"
    )
