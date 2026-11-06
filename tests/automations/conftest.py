import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from server.core import Core
from server.paths import DataDir
from server.automations import mount
from server.automations.cli import build_parser


@pytest.fixture
def auto(tmp_path):
    def require(request:Request):
        if request.headers.get('authorization') != 'Bearer test': raise HTTPException(401)
    events=[]
    core=Core(paths=DataDir(tmp_path), auth=None, require=require, emit=events.append, claude=lambda:None)
    app=FastAPI(); mount(app,core)
    manager=core.modules['automations']
    with TestClient(app, headers={'authorization':'Bearer test'}) as client:
        yield SimpleNamespace(manager=manager, db=manager.db, cfg=manager.cfg, core=core, client=client,
                              events=events, root=tmp_path, scripts=tmp_path/'automations/scripts')


@pytest.fixture
def script(auto):
    def add(name='job', kind='cron', filename=None, content='echo ok\n'):
        relative=f'{kind}/{name}/{filename or name+".sh"}'
        path=auto.scripts/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content)
        return relative
    return add


@pytest.fixture
def cli(auto):
    def invoke(*words):
        out,err=io.StringIO(),io.StringIO()
        with patch('server.automations.cli._load', return_value=(auto.cfg, auto.manager.config.path, auto.db)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            args=build_parser().parse_args(words); code=args.func(args)
        return code,out.getvalue()+err.getvalue()
    return invoke
