import logging, threading, time
from croniter import croniter
from .runner import Runner
from .timezone import local_datetime

log = logging.getLogger('automations.scheduler')


def compute_next_run(task, now=None):
    now = time.time() if now is None else now
    if task.get('task_kind', 'recurring') == 'one_off':
        if task.get('one_off_state') != 'pending' or not task.get('enabled'): return None
        try: return float(task['scheduled_at'])
        except (KeyError, TypeError, ValueError): return None
    if task.get('schedule_type') == 'cron':
        try: return croniter(task['schedule_value'], local_datetime(now)).get_next(float)
        except Exception:
            log.exception('bad cron expr for task %s', task.get('name')); return None
    if task.get('schedule_type') == 'interval':
        try: interval = float(task['schedule_value'])
        except (TypeError, ValueError): return None
        nxt = (task.get('last_run_at') or task.get('created_at') or now) + interval
        return max(nxt, now)
    return None


class Scheduler:
    def __init__(self, cfg, db):
        self.cfg, self.db, self.runner = cfg, db, Runner(cfg, db)
        self._stop = threading.Event(); self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name='automations-scheduler'); self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            try: self._tick()
            except Exception: log.exception('scheduler tick failed')
            self._stop.wait(float(self.cfg.get('poll_interval_sec', 2)))

    def _tick(self):
        now = time.time()
        for task in self.db.list_tasks():
            if task.get('running_pid') and not self.runner.reconcile(task): task = self.db.get_task(task['id'])
            if task.get('task_kind') == 'one_off': self._tick_one_off(task, now); continue
            if not task.get('enabled') or task.get('schedule_type') not in ('cron', 'interval') or task.get('running_pid'): continue
            nxt = task.get('next_run_at')
            if nxt is None:
                nxt = compute_next_run(task, now)
                if nxt is not None: self.db.update_task(task['id'], next_run_at=nxt)
                continue
            if nxt <= now:
                self.runner.run_task(task, trigger=task['schedule_type'])
                fresh = self.db.get_task(task['id']); self.db.update_task(task['id'], next_run_at=compute_next_run(fresh, now + .001))

    def _tick_one_off(self, task, now):
        if not task.get('enabled') or task.get('one_off_state') != 'pending' or task.get('running_pid'): return
        try: due = float(task.get('scheduled_at'))
        except (TypeError, ValueError):
            self.db.update_task(task['id'], enabled=0, next_run_at=None, one_off_state='failed'); return
        if due > now:
            if task.get('next_run_at') != due: self.db.update_task(task['id'], next_run_at=due)
            return
        claimed = self.db.claim_one_off(task['id'])
        if claimed: self._run_claimed_one_off(claimed, 'once_scheduled')

    def _run_claimed_one_off(self, task, trigger):
        try: return self.runner.run_task(task, trigger=trigger)
        except Exception:
            self.db.complete_one_off(task['id'], -1); raise

    def run_one_off_now(self, task):
        claimed = self.db.claim_one_off(task['id'], allow_early=True)
        return self._run_claimed_one_off(claimed, 'once_immediate') if claimed else None

    def run_now(self, task, extra_args=None, stdin_data=None):
        return self.runner.run_task(task, trigger='manual', extra_args=extra_args, stdin_data=stdin_data)

    def run_webhook(self, task, payload):
        return self.runner.run_task(task, trigger='webhook', stdin_data=payload)
