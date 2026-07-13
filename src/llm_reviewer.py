"""
Layer 2 — LLM judgment for edge cases the rule engine can't confidently classify.

Backend: DeepSeek (OpenAI-compatible API).

Iteration history:
  v1 (initial):    77% suspicious rate — classic alert-fatigue failure.
                   The LLM found problems in every voucher because the prompt
                   over-encouraged 'look for issues'.
  v2 (calibrated): 7% suspicious rate — over-corrected. Dropped TP from 26 to 7.
                   LLM interpreted 'don't duplicate rule flags in concerns' as
                   'ignore rule flags entirely and mark clean'.
  v3 (current):    Enforces rule-engine sync — rule flags force at least
                   suspicious. Preserves LLM's independent semantic judgment for
                   cases rules can't catch. Explicit anti-pattern + should-flag
                   lists calibrate what to look for vs what to ignore.

Cost: ~¥0.007 per voucher on deepseek-chat.
"""
from __future__ import annotations
import os
import sys
import json
from pathlib import Path
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from schema import Voucher, Anomaly
from rules import review_voucher, load_vouchers

# ---------- Config ----------

_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")

MODEL = "deepseek-chat"

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)


# ---------- Tool schema ----------

FLAG_VOUCHER_TOOL = {
    "type": "function",
    "function": {
        "name": "flag_voucher",
        "description": "Emit a structured second-opinion assessment of a voucher's compliance risk.",
        "parameters": {
            "type": "object",
            "properties": {
                "overall_assessment": {
                    "type": "string",
                    "enum": ["clean", "suspicious", "concerning"],
                },
                "concerns": {
                    "type": "array",
                    "maxItems": 3,
                    "description": "Specific, actionable concerns (max 3, no duplicates). Do NOT duplicate what the rule engine already flagged.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "aspect": {"type": "string"},
                            "reasoning": {"type": "string", "description": "One sentence only"},
                            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                        "required": ["aspect", "reasoning", "severity"],
                    },
                },
                "recommended_action": {
                    "type": "string",
                    "enum": ["auto_approve", "human_review", "reject"],
                },
                "confidence": {
                    "type": "number",
                    "description": "0.0 to 1.0",
                },
                "notes_to_reviewer": {
                    "type": "string",
                    "description": "Max 2 sentences.",
                },
            },
            "required": [
                "overall_assessment",
                "concerns",
                "recommended_action",
                "confidence",
                "notes_to_reviewer",
            ],
        },
    },
}


class LLMAssessment(BaseModel):
    voucher_id: str
    overall_assessment: str
    concerns: List[dict]
    recommended_action: str
    confidence: float
    notes_to_reviewer: str


# ---------- System prompt (v3 — rule-engine sync + calibrated) ----------

SYSTEM_PROMPT = """你是一位资深的财务合规分析师，专门为香港中小型金融机构的会计凭证提供二次意见。

【核心原则】
1. 尊重规则引擎：规则引擎已经识别的问题是本次评估的基础事实，不容忽略
2. 默认干净：对于规则引擎未标记的凭证，默认判断为 clean
3. 具体可行动：如果标记 suspicious，必须能指出具体、可核实的问题

【与规则引擎的同步要求（严格执行）】
- 规则引擎标记了任何 RED 或 YELLOW 级问题的凭证：overall_assessment 必须至少为 suspicious
- 即使你认为规则引擎的判断过于严格，也不得将其降级为 clean
- 只有当规则引擎未标记任何问题、且你也未发现语义级异常时，才能判定为 clean
- 你可以将 YELLOW 升级为 concerning（当你看到规则引擎未抓到的额外恶化因素时）
- concerns 数组不需要复述规则引擎已经说明的具体问题（省 tokens），但 overall_assessment 必须反映这些问题的存在

【三级判断标准】
- clean：规则引擎未标记 AND 你未发现语义级异常
  例：借贷平衡、摘要与科目匹配、tag 齐全、金额合理
  预期分布：50-65% 的凭证
  
- suspicious：满足以下任一条件即可
  (a) 规则引擎标记了任何 RED 或 YELLOW 级问题，或
  (b) 你独立发现了规则引擎未识别的具体语义级问题
  预期分布：30-45% 的凭证
  
- concerning：规则引擎标记了 RED 级问题 AND 你发现了额外恶化因素
  例：R002 附单据=0 + 摘要模糊 + 金额刚好卡在审批阈值下方
  预期分布：0-10%（较罕见）

【绝对不要独立标记为可疑的情况】
（除非规则引擎已标记；这些是财务实践中的正常现象）
- 金额精确到角分（如 3,845.09 HKD）：正常商业金额本就有小数
- 客商/摘要使用代号（如「某某电讯」「某某储蓄户」）：本数据集为脱敏样本
- 摘要为「某某电讯货款」而科目为「办公费」：电信服务归入办公费是合法处理
- 内部转账两笔分录都在银行存款科目下：正常的银行账户资金调拨
- 系统生成凭证（如月末折旧计提）无附单据、无客商 tag：常态

【应该独立标记（规则引擎未标但你观察到问题）】
- 摘要与业务性质、金额数量级严重不符
- 明显的跨字段矛盾（例如境内差旅费但人员档案显示海外常驻）
- 可疑的凑整金额恰好卡在审批阈值下方（如 29,999 港币刚好在 30,000 阈值下）
- 借贷方向逻辑错误（尽管数值可能平衡）
- 同一实体在短期内的异常密集付款模式

【输出规范】
- concerns 数组最多 3 项，最少 0 项
  - overall_assessment=clean：concerns 应为空
  - suspicious 仅因规则引擎标记：concerns 可为空，notes_to_reviewer 简述认同规则引擎的判断
  - suspicious 且有独立发现：将独立发现列入 concerns（不复述规则引擎已识别的问题）
- 每个 reasoning 用 1 句话
- notes_to_reviewer 最多 2 句话
- 一次生成，不反复推敲

通过调用 flag_voucher 工具输出结构化结果。"""


# ---------- Core (with retry) ----------

def _do_one_call(voucher: Voucher, rules_summary: str) -> LLMAssessment:
    voucher_json = voucher.model_dump_json(indent=2)
    user_message = f"""请评估以下凭证：

<voucher>
{voucher_json}
</voucher>

<rules_output>
{rules_summary}
</rules_output>

请调用 flag_voucher 工具输出评估结果。"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        tools=[FLAG_VOUCHER_TOOL],
        tool_choice={"type": "function", "function": {"name": "flag_voucher"}},
        max_tokens=1500,
        temperature=0,
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise RuntimeError(
            f"LLM did not call flag_voucher tool. Response content: {message.content}"
        )
    tool_call = message.tool_calls[0]
    if tool_call.function.name != "flag_voucher":
        raise RuntimeError(f"Unexpected tool call: {tool_call.function.name}")

    args = json.loads(tool_call.function.arguments)
    return LLMAssessment(voucher_id=voucher.voucher_id, **args)


def review_with_llm(voucher: Voucher, rules_anomalies: List[Anomaly]) -> LLMAssessment:
    """Get an LLM second-opinion. Retries once on JSON parse failure."""
    if rules_anomalies:
        rules_summary = "\n".join(
            f"- [{a.rule_id}] {a.severity.upper()}: {a.title} — {a.detail}"
            for a in rules_anomalies
        )
    else:
        rules_summary = "（规则引擎未标记任何问题）"

    try:
        return _do_one_call(voucher, rules_summary)
    except (json.JSONDecodeError, RuntimeError):
        return _do_one_call(voucher, rules_summary)


# ---------- Demo runner ----------

def _pretty_print(v: Voucher, injected, anomalies, a: LLMAssessment):
    print("=" * 72)
    print(f"Voucher {v.voucher_id}  ({v.voucher_type}, {v.source_system}, ¥{v.total_amount})")
    if injected:
        print(f"  [Injected label: {injected}]")
    print(f"  Rules: {len(anomalies)} flag(s)")
    for x in anomalies:
        print(f"    - [{x.rule_id}] {x.title}")

    print(f"\n  LLM Assessment: {a.overall_assessment.upper()}  "
          f"(action: {a.recommended_action}, confidence: {a.confidence:.2f})")
    if a.concerns:
        print(f"  Concerns:")
        for c in a.concerns:
            print(f"    - [{c['severity']}] {c['aspect']}")
            print(f"      → {c['reasoning']}")
    if a.notes_to_reviewer:
        print(f"  Note to reviewer: {a.notes_to_reviewer}")
    print()


def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY not set in .env")
        return

    data_path = Path(__file__).parent.parent / "data" / "sample_vouchers.json"
    if not data_path.exists():
        print(f"ERROR: {data_path} not found. Run data_generator.py first.")
        return

    pairs = load_vouchers(data_path)
    system_v = [(v, i) for v, i in pairs if v.is_system_generated]
    flagged  = [(v, i) for v, i in pairs if review_voucher(v) and not v.is_system_generated]
    clean    = [(v, i) for v, i in pairs if not review_voucher(v) and not v.is_system_generated]

    demo = system_v[:1] + flagged[:2] + clean[:2]

    print(f"LLM Layer 2 demo — reviewing {len(demo)} vouchers")
    print(f"Backend: DeepSeek ({MODEL})")
    print(f"Prompt version: v3 (rule-engine sync + calibrated)\n")

    for v, injected in demo:
        anomalies = review_voucher(v)
        print(f"Calling LLM for voucher {v.voucher_id}...", flush=True)
        try:
            assessment = review_with_llm(v, anomalies)
            _pretty_print(v, injected, anomalies, assessment)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
