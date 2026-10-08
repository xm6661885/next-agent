"""Probe real SDK behavior: mid-turn query (steer vs queue), can_use_tool payloads, memory."""
import asyncio, json, os, sys, time
from claude_agent_sdk import (ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, UserMessage,
    ResultMessage, SystemMessage, StreamEvent, TextBlock, ToolUseBlock, PermissionResultAllow)

T0 = time.monotonic()
def log(*a): print(f"[{time.monotonic()-T0:6.1f}s]", *a, flush=True)

async def can_use_tool(name, inp, ctx):
    log("CAN_USE_TOOL", name, json.dumps(inp)[:300], "suggestions=", [getattr(s, "type", s) for s in ctx.suggestions])
    if name == "AskUserQuestion":
        q = inp["questions"][0]
        return PermissionResultAllow(updated_input={"questions": inp["questions"],
            "answers": {q["question"]: q["options"][0]["label"]}})
    return PermissionResultAllow()

def rss_of_children():
    tot = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit(): continue
        try:
            st = open(f"/proc/{pid}/status").read()
            if f"PPid:\t{os.getpid()}\n" in st:
                tot += int([l for l in st.splitlines() if l.startswith("VmRSS")][0].split()[1])
        except Exception: pass
    return tot // 1024

async def main():
    opts = ClaudeAgentOptions(cwd="/tmp", permission_mode="default",
        can_use_tool=can_use_tool, include_partial_messages=True,
        system_prompt={"type": "preset", "preset": "claude_code"}, setting_sources=["user"], effort="low", extra_args={"replay-user-messages": None})
    async with ClaudeSDKClient(opts) as c:
        log("connected, child RSS MB:", rss_of_children())
        async def pump():
            async for m in c.receive_messages():
                if isinstance(m, StreamEvent): continue
                if isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, TextBlock): log("ASSIST TEXT:", b.text[:200].replace("\n"," "))
                        elif isinstance(b, ToolUseBlock): log("TOOL_USE", b.name, json.dumps(b.input)[:150])
                elif isinstance(m, UserMessage):
                    log("USER msg uuid=", m.uuid, type(m.content).__name__, str(m.content)[:120].replace("\n"," "))
                elif isinstance(m, SystemMessage):
                    log("SYSTEM", m.subtype, list(m.data.keys())[:20] if m.subtype=="init" else str(m.data)[:150])
                elif isinstance(m, ResultMessage):
                    log("RESULT", m.subtype, m.num_turns, m.total_cost_usd, getattr(m, "terminal_reason", None), m.session_id)
                else:
                    log("OTHER", type(m).__name__)
        pt = asyncio.create_task(pump())
        await c.query("Run these bash commands one at a time as separate tool calls: `sleep 4; echo A`, then `sleep 4; echo B`, then `sleep 4; echo C`. Then summarize.")
        await asyncio.sleep(18)
        log("--> sending mid-turn message, child RSS MB:", rss_of_children())
        await c.query("STEER: also tell me the word BANANA in your final summary.")
        await asyncio.sleep(40)
        log("final child RSS MB:", rss_of_children())
        pt.cancel()

asyncio.run(main())
