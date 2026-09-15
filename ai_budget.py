"""Reserve estimated spend atomically BEFORE every provider request.

Only counters are stored, never listing data or credentials. SQLite coordinates
sessions/processes sharing this file. Use persistent storage across redeploys.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
import math
import os
from pathlib import Path
import sqlite3

DB_PATH = Path(os.getenv('AI_USAGE_DB', str(Path(__file__).with_name('.ai_usage.sqlite3'))))


class BudgetBlocked(RuntimeError):
    pass


def units(value):
    if not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError('Budget values must be finite and nonnegative')
    return int((Decimal(str(value)) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def _connect():
    db = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS usage (bucket TEXT PRIMARY KEY, cost INTEGER NOT NULL, calls INTEGER NOT NULL)')
    except Exception:
        db.close()
        raise
    return db


def _buckets(scan_id):
    today = datetime.now(timezone.utc).date().isoformat()
    return ['scan:' + scan_id, 'day:' + today, 'month:' + today[:7]]


def _migrate(db):
    if db.execute("SELECT 1 FROM usage WHERE bucket='legacy-import'").fetchone():
        return
    legacy = DB_PATH.with_name('.vision_usage.json')
    if legacy.exists():
        data = json.loads(legacy.read_text(encoding='utf-8'))
        for period in ('day', 'month'):
            if data.get(period):
                db.execute('INSERT OR IGNORE INTO usage VALUES (?,?,?)',
                           (period + ':' + data[period], units(data.get(period + '_cost', 0)), int(data.get(period + '_calls', 0))))
    db.execute("INSERT INTO usage VALUES ('legacy-import',0,0)")


def reserve(scan_id, max_calls, scan_budget, daily_budget, monthly_budget, cost):
    """No refund on failures: a timeout may still have incurred a charge."""
    charge = units(cost)
    if charge <= 0:
        raise BudgetBlocked('Set a positive estimated cost per analysis')
    db = None
    try:
        db = _connect()
        db.execute('BEGIN IMMEDIATE')
        _migrate(db)
        buckets = _buckets(scan_id)
        limits = [units(scan_budget), units(daily_budget), units(monthly_budget)]
        for i, bucket in enumerate(buckets):
            spent, calls = db.execute('SELECT cost,calls FROM usage WHERE bucket=?', (bucket,)).fetchone() or (0, 0)
            if i == 0 and calls >= max_calls:
                raise BudgetBlocked('Per-scan analysis limit reached')
            if spent + charge > limits[i]:
                raise BudgetBlocked(['Per-scan budget reached', 'Daily budget reached', 'Monthly budget reached'][i])
        for bucket in buckets:
            db.execute('INSERT INTO usage VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET cost=cost+excluded.cost,calls=calls+1', (bucket, charge))
        db.execute('COMMIT')
    except BudgetBlocked:
        raise
    except Exception as exc:
        raise BudgetBlocked('AI paused: budget ledger could not be read or saved') from exc
    finally:
        if db is not None:
            if db.in_transaction:
                db.execute('ROLLBACK')
            db.close()


def snapshot(scan_id):
    db = _connect()
    try:
        result = {}
        for label, bucket in zip(('scan', 'today', 'month'), _buckets(scan_id)):
            cost, calls = db.execute('SELECT cost,calls FROM usage WHERE bucket=?', (bucket,)).fetchone() or (0, 0)
            result['estimated_' + label + '_cost'] = cost / 1_000_000
            result[label + '_calls'] = calls
        result['calls_this_scan'] = result['scan_calls']
        return result
    finally:
        db.close()
