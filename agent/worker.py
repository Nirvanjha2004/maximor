"""The Worker Agent: an LLM with tool access that triages each invoice.

Runs one conversation per invoice, calling the fake AP system's tools until it
records a final decision. Relevant playbook lessons are injected into the
system prompt for this invoice only (tag-routed memory keeps prompts small).
"""
import json
import time

import anthropic

from .config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK
from .tools import APSystem, TOOL_IMPLS, TOOL_SPECS

SYSTEM_BASE = """You are an accounts-payable (AP) triage agent for a mid-size company.

For the single invoice you are given, decide exactly one of:
- APPROVE  (pay it)
- REJECT   (do not pay; e.g. duplicate)
- ESCALATE (route to a human for review)

You MUST use the provided tools to look up the vendor, the PO, prior invoice
history, and the AP policy rulebook before deciding. Base every decision on the
policies (POL-001..POL-007) - never guess. When you are done, call
record_decision with a short reason citing the policy that drove your decision.
If the AP PLAYBOOK section is present below, treat every lesson in it as
mandatory guidance learned from previous mistakes - apply it.
"""


def run_invoice(ap: APSystem, invoice: dict, playbook_text: str, model: str = None,
                max_turns: int = 12) -> dict:
    """Triage one invoice. Returns per-invoice metrics."""
    model = model or ANTHROPIC_MODEL
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system = SYSTEM_BASE + (f"\n\n{playbook_text}" if playbook_text else "")
    messages = [{"role": "user",
                 "content": (f"Triage this invoice:\n{json.dumps(invoice)}\n\n"
                             f"Look up everything you need, then record_decision.")}]
    t0 = time.time()
    usage_in = usage_out = tool_calls = 0
    for _ in range(max_turns):
        resp = client.messages.create(model=model, max_tokens=1024, system=system,
                                      tools=TOOL_SPECS, messages=messages)
        usage_in += resp.usage.input_tokens
        usage_out += resp.usage.output_tokens
        if resp.stop_reason != "tool_use":
            break
        tool_calls += len([b for b in resp.content if b.type == "tool_use"])
        blocks = []
        for block in resp.content:
            if block.type == "tool_use":
                args = block.input or {}
                result = TOOL_IMPLS[block.name](ap, args)
                blocks.append({"type": "tool_result", "tool_use_id": block.id,
                               "content": json.dumps(result)})
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": blocks})
    latency = round(time.time() - t0, 2)
    cost = round(usage_in / 1e6 * PRICE_IN_PER_MTOK + usage_out / 1e6 * PRICE_OUT_PER_MTOK, 6)
    return {"invoice_id": invoice["id"], "tool_calls": tool_calls, "latency_s": latency,
            "tokens_in": usage_in, "tokens_out": usage_out, "cost_usd": cost}
