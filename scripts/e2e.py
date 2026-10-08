"""End-to-end check against a running server with the real Claude CLI (costs a few cents).

Usage: NEXT_AGENT_PASSWORD=... uv run python scripts/e2e.py [base_url]   (default http://[::1]:18793)
"""
import asyncio, json, os, sys, time
import httpx, websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://[::1]:18793"
WS = BASE.replace("http", "ws", 1)
PW = os.environ["NEXT_AGENT_PASSWORD"]
T0 = time.monotonic()
def log(*a): print(f"[{time.monotonic()-T0:6.1f}s]", *a, flush=True)

class Sock:
    def __init__(self, sid, cookie):
        self.sid, self.cookie, self.events, self.seq = sid, cookie, [], 0
    async def open(self, seq=None):
        self.ws = await websockets.connect(f"{WS}/ws/sessions/{self.sid}", origin=BASE.replace("[::1]", "[::1]"),
                                           additional_headers={"Cookie": self.cookie, "Host": BASE.split("//")[1]})
        await self.ws.send(json.dumps({"type": "resume", "seq": seq}))
        self.task = asyncio.create_task(self._read())
    async def _read(self):
        try:
            async for raw in self.ws:
                ev = json.loads(raw); self.events.append(ev); self.seq = max(self.seq, ev.get("seq") or 0)
        except websockets.ConnectionClosed: pass
    async def send(self, **m): await self.ws.send(json.dumps(m))
    async def close(self): await self.ws.close(); self.task.cancel()
    async def wait(self, pred, timeout=180, start=0):
        t = time.monotonic()
        while time.monotonic() - t < timeout:
            for ev in self.events[start:]:
                if pred(ev): return ev
            await asyncio.sleep(0.2)
        raise TimeoutError("condition not met")

def is_state(s): return lambda e: e.get("type") == "state" and e["state"] == s

async def main():
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.post("/api/login", json={"password": PW}); r.raise_for_status()
        cookie = f"na_auth={c.cookies['na_auth']}"
        aid = "e2e-test"
        await c.delete(f"/api/agents/{aid}")
        r = await c.post("/api/agents", json={"id": aid, "name": "E2E Test", "cwd": "/tmp/na-e2e", "effort": "low",
                                              "permission_mode": "bypassPermissions"}); r.raise_for_status()
        sid = (await c.post(f"/api/agents/{aid}/sessions", json={})).json()["id"]
        log("session", sid)

        # 1. streaming + steer
        s = Sock(sid, cookie); await s.open()
        await s.wait(lambda e: e["type"] == "snapshot")
        await s.send(type="send", client_id="c1", text="Run `sleep 3; echo A` with Bash, then `sleep 3; echo B`, then reply with one short sentence.", attachments=[])
        await s.wait(lambda e: e["type"] == "item" and e["item"]["kind"] == "tool")
        log("tool started; steering")
        await s.send(type="send", client_id="c2", text="Also include the word BANANA.", attachments=[])
        await s.wait(lambda e: e["type"] == "patch" and e["patch"].get("pending") is False and e["patch"].get("uuid"))
        log("steer consumed")
        # 2. drop the socket mid-turn and resume later
        await s.close(); last = s.seq; log("socket closed at seq", last)
        await asyncio.sleep(8)
        s2 = Sock(sid, cookie); await s2.open(seq=last)
        res = await s2.wait(lambda e: e["type"] == "item" and e["item"]["kind"] == "result", timeout=240)
        texts = "".join(e.get("text", "") for e in s.events + s2.events if e["type"] == "delta" and e["field"] == "text")
        log("result", res["item"]["subtype"], "cost", res["item"]["cost_usd"], "| BANANA in text:", "BANANA" in texts.upper())
        log("replayed events after resume:", len(s2.events), "snapshot?", any(e["type"] == "snapshot" for e in s2.events))
        await s2.wait(is_state("idle"))

        # 3. permission request in default mode
        await s2.send(type="set_mode", mode="default")
        await asyncio.sleep(1)
        n = len(s2.events)
        await s2.send(type="send", client_id="c3", text="Create a file named hello.txt containing hi, using the Write tool.", attachments=[])
        p = await s2.wait(lambda e: e["type"] == "permission", start=n)
        log("permission request:", p["request"]["kind"], p["request"]["tool_name"])
        await s2.send(type="permission_reply", id=p["request"]["id"], decision="allow")
        await s2.wait(lambda e: e["type"] == "permission_resolved", start=n)
        await s2.wait(lambda e: e["type"] == "item" and e["item"]["kind"] == "result", start=n, timeout=240)
        import os; log("hello.txt exists:", os.path.exists("/tmp/na-e2e/hello.txt"))

        # 4. interrupt
        n = len(s2.events)
        await s2.send(type="set_mode", mode="bypassPermissions")
        await s2.send(type="send", client_id="c4", text="Run `sleep 30` with Bash.", attachments=[])
        await s2.wait(lambda e: e["type"] == "item" and e["item"]["kind"] == "tool", start=n)
        await asyncio.sleep(2)
        await s2.send(type="interrupt")
        res = await s2.wait(lambda e: e["type"] == "item" and e["item"]["kind"] == "result", start=n, timeout=60)
        log("interrupt result:", res["item"]["subtype"], res["item"].get("terminal_reason"))
        await s2.close()

        # 5. history after reconnect (fresh snapshot)
        s3 = Sock(sid, cookie); await s3.open()
        snap = await s3.wait(lambda e: e["type"] == "snapshot")
        kinds = {}
        for it in snap["items"]: kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        log("snapshot items:", kinds, "state", snap["state"])
        await s3.close()
        sess = (await c.get(f"/api/sessions/{sid}")).json()
        log("session:", sess["title"], "turns", sess["turns"], "cost", round(sess["total_cost_usd"], 4), "ctx", sess["context"])
        status = (await c.get("/api/status")).json(); log("status:", status)

asyncio.run(main())
