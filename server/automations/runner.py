"""Detached workers, with the AutoTask script execution and stop semantics."""
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger('automations.runner')


class ScriptError(ValueError):
    pass


def resolve_script(scripts_dir, script):
    root = os.path.realpath(scripts_dir)
    path = os.path.realpath(os.path.join(root, script))
    if os.path.commonpath([root, path]) != root:
        raise ScriptError(f'script path escapes scripts_dir: {script}')
    if not os.path.isfile(path):
        raise ScriptError(f'script not found: {script}')
    return path


def interpreter_for(path, cfg):
    if path.endswith('.py'): return [cfg['python_bin']]
    if path.endswith('.sh'): return [cfg['shell_bin']]
    if os.access(path, os.X_OK): return []
    raise ScriptError(f'unsupported script type (need .py/.sh or +x): {path}')


def launch_worker(argv, task_id, run_id, data_root, ready):
    env = os.environ.copy()
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{os.getuid()}/bus')
    env['NEXT_AGENT_DATA'] = str(data_root)
    repo = str(Path(__file__).resolve().parents[2])
    env['PYTHONPATH'] = repo + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    options = dict(env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    scope = ['systemd-run', '--user', '--scope', '--collect', '--quiet',
             '--unit', f'autotask-{task_id}-{run_id}', '--', *argv]
    # A scope's launcher stays alive until the worker exits. Its successful
    # Popen alone does not mean systemd accepted the scope (e.g. no user bus).
    try:
        proc = subprocess.Popen(scope, **options)
        while not ready.exists():
            code = proc.poll()
            if code is not None: raise OSError(f'systemd-run exited {code} before worker startup')
            time.sleep(.02)
    except OSError as exc:
        log.warning('systemd-run unavailable; using detached worker: %s', exc)
        proc = subprocess.Popen(argv, **options)
        while not ready.exists():
            code = proc.poll()
            if code is not None: raise ScriptError(f'worker exited {code} before startup')
            time.sleep(.02)
    ready.unlink()
    # Reap the launcher only; shutdown never waits for or stops task workers.
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc.pid


class Runner:
    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db
        self.worker_pid = None

    def run_task(self, task, trigger='manual', extra_args=None, stdin_data=None):
        if task.get('task_kind') == 'one_off' and task.get('one_off_state') != 'running':
            raise ScriptError('one-off task must be claimed before it can run')
        script = resolve_script(self.cfg['scripts_dir'], task['script'])
        command = interpreter_for(script, self.cfg) + [script] + json.loads(task.get('args') or '[]') + list(extra_args or [])
        root = Path(self.cfg['data_dir'])
        logs = root / 'logs'; logs.mkdir(parents=True, exist_ok=True)
        tmp = root / 'tmp'; tmp.mkdir(parents=True, exist_ok=True)
        log_path = logs / f"{task['name']}-{time.strftime('%Y%m%d-%H%M%S')}.log"
        run_id = self.db.create_run(task['id'], trigger, str(log_path))
        payload_file = None
        ready = tmp / f'{run_id}.ready'
        try:
            if stdin_data is not None:
                fd, name = tempfile.mkstemp(prefix=f'{run_id}-', dir=tmp)
                payload_file = Path(name)
                with os.fdopen(fd, 'wb') as stream: stream.write(stdin_data)
            argv = [sys.executable, '-m', 'server.automations.cli', '_execute-task', str(task['id']),
                    '--run-id', str(run_id), '--extra-args-json', json.dumps(extra_args or []),
                    '--command-json', json.dumps(command), '--cwd', os.path.dirname(script),
                    '--ready-file', str(ready)]
            if payload_file: argv += ['--payload-file', str(payload_file)]
            self.worker_pid = launch_worker(argv, task['id'], run_id, root.parent, ready)
        except (OSError, ScriptError):
            self.db.finish_run(run_id, -1)
            self.db.update_task(task['id'], running_pid=None, last_run_at=time.time())
            if task.get('task_kind') == 'one_off': self.db.complete_one_off(task['id'], -1)
            if payload_file: payload_file.unlink(missing_ok=True)
            ready.unlink(missing_ok=True)
            raise
        return run_id

    def execute_run(self, task, run_id, log_path, command, payload_file=None, cwd=None):
        exit_code = -1
        try:
            payload = Path(payload_file).read_bytes() if payload_file else None
            if payload_file: Path(payload_file).unlink()
            env = os.environ.copy()
            python_dir = os.path.dirname(self.cfg['python_bin'])
            if os.path.isdir(python_dir):
                env['PATH'] = python_dir + (os.pathsep + env['PATH'] if env.get('PATH') else '')
            with open(log_path, 'wb') as logf:
                logf.write(f"$ {' '.join(command)}\n".encode()); logf.flush()
                proc = subprocess.Popen(command, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                    stdout=logf, stderr=subprocess.STDOUT,
                    cwd=cwd or os.path.dirname(resolve_script(self.cfg['scripts_dir'], task['script'])),
                    env=env, start_new_session=True)
                self.db.update_task(task['id'], running_pid=proc.pid)
                if payload is not None:
                    proc.stdin.write(payload); proc.stdin.close()
                exit_code = proc.wait()
        except Exception as exc:
            try:
                with open(log_path, 'ab') as logf: logf.write(f'\n[autotask] execution error: {exc}\n'.encode())
            except OSError:
                pass  # The log itself can be the failing resource.
        finally:
            self.db.update_task(task['id'], running_pid=None, last_run_at=time.time())
            self.db.finish_run(run_id, exit_code)
            if task.get('task_kind') == 'one_off': self.db.complete_one_off(task['id'], exit_code)
            if payload_file: Path(payload_file).unlink(missing_ok=True)
        return exit_code

    def stop_task(self, task):
        pid = task.get('running_pid')
        if not pid: return False
        try: os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._reconcile_dead(task); return False
        except PermissionError: return False
        return True

    def _reconcile_dead(self, task):
        self.db.update_task(task['id'], running_pid=None)
        run = self.db.get_open_run(task['id'])
        if run: self.db.finish_run(run['id'], None)

    def reconcile(self, task):
        pid = task.get('running_pid')
        if not pid: return False
        try: os.kill(pid, 0); return True
        except ProcessLookupError: self._reconcile_dead(task); return False
        except PermissionError: return True
