"""Side questions ("/btw"): one tool-less turn on a throwaway fork of the session transcript."""
import dataclasses
from claude_agent_sdk import query
from claude_agent_sdk.types import StreamEvent, AssistantMessage, TextBlock
from .options import build_options

SYSTEM = """You are answering a "by the way" side question in a web console for Claude Code agents.

The conversation above is the transcript of a main agent session that may still be running. You are not that agent and you are not continuing its task. The user opened a small side window to ask you something about it, for example what the agent is doing, why it made a choice, what a term or piece of code means, or a quick general question.

- Answer the question directly. Lead with the answer and keep it short unless the user asks for depth.
- Base answers about the session on the transcript. If the transcript does not show something, say so instead of guessing.
- You have no tools and cannot act: do not read files, run commands, edit code or promise to do so. If the user wants something done, tell them to send it to the main agent.
- Do not resume, summarize or comment on the main task unless asked.
- Reply in the language the user writes in. Markdown is fine."""

def prompt(question, history=()):
    """Earlier side exchanges ride along in the prompt; each ask is a fresh unpersisted fork."""
    past = ''.join(f'<earlier_side_question>\n{h["q"]}\n</earlier_side_question>\n<your_earlier_answer>\n{h["a"]}\n</your_earlier_answer>\n\n'
                   for h in history if h.get('q'))
    return (past + '<side_question>\n' + question + '\n</side_question>') if past else question

def btw_options(agent, session, resume, defaults, server_cfg, custom_md_path=None, model=None):
    opts = build_options(agent, session, defaults, server_cfg, None, resume=resume, fork=True,
                         custom_md_path=custom_md_path)
    extra = {k: v for k, v in opts.extra_args.items() if k != 'replay-user-messages'}
    extra['no-session-persistence'] = None
    return dataclasses.replace(opts, tools=[], allowed_tools=[], disallowed_tools=[], mcp_servers={}, agents=None,
                               max_turns=1, extra_args=extra, system_prompt=SYSTEM,
                               model=model or opts.model, enable_file_checkpointing=False)

async def ask(opts, question, history=()):
    """Yield the reply text in chunks."""
    streamed = False
    async for msg in query(prompt=prompt(question, history), options=opts):
        if isinstance(msg, StreamEvent):
            ev = msg.event
            if ev.get('type') == 'content_block_delta' and ev.get('delta', {}).get('type') == 'text_delta':
                streamed = True
                yield ev['delta']['text']
        elif isinstance(msg, AssistantMessage) and not streamed:
            for b in msg.content:
                if isinstance(b, TextBlock): yield b.text
