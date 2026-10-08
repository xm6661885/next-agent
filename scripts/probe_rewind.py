"""Probe a truncating resume against the bundled Claude CLI."""
import asyncio
import json
import shutil
from pathlib import Path
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, UserMessage, AssistantMessage, ResultMessage, TextBlock, get_session_messages
from server.history import transcript_path

CWD = Path('/tmp/na-probe-rewind')

async def turn(client, prompt):
    await client.query(prompt)
    user = None
    answer = []
    result = None
    async for msg in client.receive_response():
        if isinstance(msg, UserMessage) and msg.uuid: user = msg.uuid
        if isinstance(msg, AssistantMessage):
            answer.extend(block.text for block in msg.content if isinstance(block, TextBlock))
        if isinstance(msg, ResultMessage): result = msg
    return user, ' '.join(answer), result

async def main():
    shutil.rmtree(CWD, ignore_errors=True)
    CWD.mkdir()
    options = dict(cwd=str(CWD), setting_sources=['user'], permission_mode='bypassPermissions',
                   effort='low', extra_args={'replay-user-messages':None}, include_partial_messages=False)
    try:
        async with ClaudeSDKClient(ClaudeAgentOptions(**options)) as client:
            u1, a1, r1 = await turn(client, 'Remember the word APPLE. Reply with just OK.')
            u2, a2, r2 = await turn(client, 'Remember the word BANANA. Reply with just OK.')
        sid = r2.session_id
        path = transcript_path(sid, str(CWD))
        entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        entry = next(x for x in entries if x.get('uuid') == u2)
        parent = entry.get('parentUuid')
        before = len(entries)
        async with ClaudeSDKClient(ClaudeAgentOptions(**options, resume=sid, resume_session_at=parent)) as client:
            u3, a3, r3 = await turn(client, 'Which words did I ask you to remember? Answer in one line.')
        entries2 = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        new_entry = next((x for x in entries2 if x.get('uuid') == u3), None)
        messages = get_session_messages(sid, directory=str(CWD))
        print('U1:', u1, 'answer:', a1)
        print('U2:', u2, 'answer:', a2)
        print('echo_equals_transcript:', entry.get('uuid') == u2)
        print('parent_of_U2:', parent)
        print('U3:', u3, 'answer:', a3)
        print('session_ids:', sid, r3.session_id, 'same:', sid == r3.session_id)
        print('same_jsonl_appended:', len(entries2) > before, 'entries:', before, '->', len(entries2))
        print('parent_of_U3:', new_entry.get('parentUuid') if new_entry else None, 'matches:', bool(new_entry and new_entry.get('parentUuid') == parent))
        print('visible_user_messages:', [(m.uuid, m.message.get('content')) for m in messages if m.type == 'user'])
    finally:
        shutil.rmtree(CWD, ignore_errors=True)

if __name__ == '__main__': asyncio.run(main())
