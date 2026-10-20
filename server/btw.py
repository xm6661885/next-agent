"""Side questions ("/btw"): one tool-less turn on a throwaway fork of the session transcript."""
import dataclasses
from claude_agent_sdk import query
from claude_agent_sdk.types import StreamEvent, AssistantMessage, TextBlock
from .options import build_options

PROMPT = ('<system-reminder>This is a side question from the user, asked while you may be busy with the main task. '
          'Answer it directly and briefly from what you already know in this conversation. You have no tools in this '
          'reply and cannot take actions; this exchange is not part of the main conversation.</system-reminder>\n\n')

def btw_options(agent, session, resume, defaults, server_cfg, custom_md_path=None):
    opts = build_options(agent, session, defaults, server_cfg, None, resume=resume, fork=True,
                         custom_md_path=custom_md_path)
    extra = {k: v for k, v in opts.extra_args.items() if k != 'replay-user-messages'}
    extra['no-session-persistence'] = None
    return dataclasses.replace(opts, tools=[], allowed_tools=[], disallowed_tools=[], mcp_servers={}, agents=None,
                               max_turns=1, extra_args=extra, enable_file_checkpointing=False)

async def ask(opts, question):
    """Yield the reply text in chunks."""
    streamed = False
    async for msg in query(prompt=PROMPT + question, options=opts):
        if isinstance(msg, StreamEvent):
            ev = msg.event
            if ev.get('type') == 'content_block_delta' and ev.get('delta', {}).get('type') == 'text_delta':
                streamed = True
                yield ev['delta']['text']
        elif isinstance(msg, AssistantMessage) and not streamed:
            for b in msg.content:
                if isinstance(b, TextBlock): yield b.text
