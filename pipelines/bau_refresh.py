#!/usr/bin/env python3
"""Build bau_data.json for Input Metrics -> Task Compliance -> BAU Metrics.

Meta and Google BAU trigger tasks. Unlike task_refresh.py these are identified by
*title* (type+sub_type alone cannot separate them: e.g. notification/
notify_growth_consultant_gc holds 200+ titles, of which only two are BAU), and
title is not a column on card 10181. So this pipeline runs inline native SQL via
/api/dataset/json against nushop.workboard_tasks, mirroring card 10181's joins.

Keeps the last 45 days, source='system'. status completed/closed = done,
pending = pending; within-SLA = tat <= sla_in_min (computed client-side).

Run: cd ~/shopdeck-metrics-site && python3 pipelines/bau_refresh.py --push
"""
import json, os, sys, subprocess, urllib.request, urllib.parse, datetime

REPO = os.path.expanduser(os.environ.get("REPO_DIR", "~/shopdeck-metrics-site"))
OUT = os.path.join(REPO, "bau_data.json")
CRED_CACHE = os.path.expanduser("~/metabase-arr-refresh/.mbcreds")
DESKTOP_CFG = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
DB = 6
WINDOW_DAYS = 45

# BAU task catalogue. code -> (channel, label, type, sub_type, title | None = any sub_type/title)
# Titles are matched lower/trimmed: the DB stores "Low stock Alert" (lowercase s).
BAU_TASKS = [
    ('m1', 'meta',   'Low Stock Alert',                 'notification',             'notify_growth_consultant_gc', 'low stock alert'),
    ('m2', 'meta',   'Meta Funds Exhaustion Alert',     'seller_marketing_restart', 'funds_diagnosis_restart',     'meta funds exhaustion alert'),
    ('m3', 'meta',   'Out Of Stock Product Found',      'notification',             'notify_growth_consultant_gc', 'out of stock product found'),
    ('m4', 'meta',   'Meta Restart Trigger - Low Spend Detected',
                                                        'seller_marketing_restart', 'funds_diagnosis_restart',     'meta restart trigger - low spend detected'),
    ('g1', 'google', 'Google Restart Trigger - Funds Available, Low Spend',
                                                        'seller_marketing_restart', 'funds_diagnosis_restart',     'google restart trigger - funds available, low spend'),
    # google_onboarding is expanded at build time into one row per onboarding step
    # (sub_type), labelled with that step's task title. See expand_catalogue().
    ('g2', 'google', 'Google Onboarding',               'google_onboarding',        None,                          None),
    ('g3', 'google', 'Troubleshoot Trigger',            'troubleshoot_action',      'troubleshoot_manual_action',  'troubleshoot trigger'),
]


def creds():
    if os.environ.get('METABASE_URL'):
        return os.environ['METABASE_URL'].rstrip('/'), os.environ.get('METABASE_USER_EMAIL'), os.environ.get('METABASE_PASSWORD')
    e = json.load(open(CRED_CACHE)) if os.path.exists(CRED_CACHE) else json.load(open(DESKTOP_CFG))['mcpServers']['metabase']['env']
    return e['METABASE_URL'].rstrip('/'), e.get('METABASE_USER_EMAIL'), e.get('METABASE_PASSWORD')


def _open(req):
    import time as _t
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            last = e
            _t.sleep(3 * (attempt + 1))
    raise last


def auth_headers(url, email, pw):
    key = os.environ.get('METABASE_API_KEY')
    if not key:
        try:
            key = json.load(open(CRED_CACHE)).get('METABASE_API_KEY')
        except Exception:
            key = None
    if key:
        return {'x-api-key': key}
    req = urllib.request.Request(url + "/api/session", data=json.dumps({"username": email, "password": pw}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    return {'X-Metabase-Session': _open(req)['id']}


def sql_filter():
    """Build the WHERE clause that selects exactly the BAU catalogue."""
    parts = []
    by_ts = {}
    for _code, _ch, _label, ty, st, title in BAU_TASKS:
        by_ts.setdefault((ty, st), []).append(title)
    for (ty, st), titles in by_ts.items():
        if st is None:
            parts.append("(t.type='%s')" % ty)
        elif any(x is None for x in titles):
            parts.append("(t.type='%s' and t.sub_type='%s')" % (ty, st))
        else:
            lst = ','.join("'%s'" % x.replace("'", "\\'") for x in titles)
            parts.append("(t.type='%s' and t.sub_type='%s' and lower(trim(t.title)) in (%s))" % (ty, st, lst))
    return ' or '.join(parts)


QUERY = """
with base as (
  select
    t.id, t.seller_id, t.type, t.sub_type, t.source, t.title, t.status, t.sla_in_min,
    date(t.created_at,'Asia/Kolkata') as task_created_at,
    date(t.completion_date,'Asia/Kolkata') as task_due_date,
    date(t.completed_at,'Asia/Kolkata') as completed_on,
    case when t.status != 'pending' then greatest(datetime_diff(t.completed_at, t.created_at, minute), 0) end as tat,
    trim(concat(coalesce(u.first_name,''),' ',coalesce(u.last_name,''))) as assignee_name,
    case
      when lower(u.role) like '%%growth-consultant%%' then 'GC'
      when lower(u.role) like '%%key-account-manager%%' then 'KAM'
      when lower(u.role) like '%%key-account-executive%%' then 'KAE'
      when lower(u.role) like '%%growth-manager%%' then 'GM'
      when lower(u.role) like '%%category-lead%%' then 'CL'
      else 'Others' end as assignee_bucket,
    trim(concat(coalesce(gm.first_name,''),' ',coalesce(gm.last_name,''))) as gm_name,
    trim(concat(coalesce(cl.first_name,''),' ',coalesce(cl.last_name,''))) as cl_name
  from nushop.workboard_tasks t
  left join nushop.users u on t.assignee = u._id
  left join nushop.seller_managers sm_gm on t.seller_id = sm_gm.seller_id and sm_gm.manager_type like '%%growth_manager%%'
  left join nushop.users gm on sm_gm.manager_id = gm._id
  left join nushop.seller_managers sm_cl on t.seller_id = sm_cl.seller_id and sm_cl.manager_type like '%%category_lead%%'
  left join nushop.users cl on sm_cl.manager_id = cl._id
  where date(t.created_at,'Asia/Kolkata') >= date_sub(current_date('Asia/Kolkata'), interval %(win)d day)
    and date(t.created_at,'Asia/Kolkata') <= current_date('Asia/Kolkata')
    and t.source = 'system'
    and (%(filt)s)
)
select * from base
"""


def tag_of(r):
    """Map a row to its BAU catalogue code, or None."""
    ty = (r.get('type') or '').strip()
    st = (r.get('sub_type') or '').strip()
    ti = (r.get('title') or '').strip().lower()
    for code, _ch, _label, cty, cst, ctitle in BAU_TASKS:
        if ty != cty:
            continue
        if cst is not None and st != cst:
            continue
        if ctitle is not None and ti != ctitle:
            continue
        return code
    return None


def d10(v):
    return str(v)[:10] if v else ''


# Catalogue codes that are broken out into one row per sub_type, labelled by task title.
EXPAND_CODES = {'g2'}


def expand_catalogue(out):
    """Split EXPAND_CODES groups into one catalogue entry per sub_type.

    Rewrites each affected task's `tg` in place to '<code>:<sub_type>' and returns
    the ordered catalogue, so a new onboarding step shows up without a code change.
    Label = the most common title seen for that sub_type.
    """
    seen = {}   # code -> {sub_type: {title: count}}
    for t in out:
        if t['tg'] in EXPAND_CODES:
            seen.setdefault(t['tg'], {}).setdefault(t['st'] or '(none)', {})
            titles = seen[t['tg']][t['st'] or '(none)']
            titles[t['ti']] = titles.get(t['ti'], 0) + 1
    for t in out:
        if t['tg'] in EXPAND_CODES:
            t['tg'] = t['tg'] + ':' + (t['st'] or '(none)')

    catalogue = []
    for code, ch, label, ty, st, ti in BAU_TASKS:
        if code not in EXPAND_CODES:
            catalogue.append({'code': code, 'channel': ch, 'label': label,
                              'ty': ty, 'st': st or '', 'ti': ti or ''})
            continue
        subs = seen.get(code, {})
        # busiest step first, so the table reads top-down by volume
        order = sorted(subs.items(), key=lambda kv: -sum(kv[1].values()))
        for sub, titles in order:
            best = max(titles.items(), key=lambda kv: kv[1])[0]
            catalogue.append({'code': code + ':' + sub, 'channel': ch,
                              'label': best or sub, 'ty': ty, 'st': sub, 'ti': best,
                              'group': label})
    return catalogue


def main():
    url, email, pw = creds()
    H = auth_headers(url, email, pw)
    sql = QUERY % {'win': WINDOW_DAYS, 'filt': sql_filter()}
    q = {"database": DB, "type": "native", "native": {"query": sql, "template-tags": {}}}
    body = urllib.parse.urlencode({"query": json.dumps(q)}).encode()
    req = urllib.request.Request(url + "/api/dataset/json", data=body, method="POST",
                                 headers={**H, "Content-Type": "application/x-www-form-urlencoded"})
    rows = _open(req)
    print("[bau] fetched %d rows" % len(rows))

    cutoff = (datetime.date.today() - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    out, skipped = [], 0
    for r in rows:
        code = tag_of(r)
        if not code:
            skipped += 1
            continue
        out.append({
            'id': str(r.get('id') or ''), 's': str(r.get('seller_id') or ''),
            'tg': code, 'b': str(r.get('assignee_bucket') or 'Others'),
            'ty': str(r.get('type') or ''), 'st': str(r.get('sub_type') or ''),
            'ti': str(r.get('title') or ''),
            'gc': str(r.get('assignee_name') or '').strip() or 'Unassigned',
            'gm': str(r.get('gm_name') or '').strip() or 'Unassigned',
            'cl': str(r.get('cl_name') or '').strip() or 'Unassigned',
            'status': str(r.get('status') or '').strip().lower(),
            'cr': d10(r.get('task_created_at')), 'du': d10(r.get('task_due_date')),
            'cp': d10(r.get('completed_on')),
            'sla': r.get('sla_in_min'), 'tat': r.get('tat'),
        })
    if skipped:
        print("[bau] %d rows did not match the catalogue (ignored)" % skipped)

    catalogue = expand_catalogue(out)
    data = {'generatedAt': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'windowDays': WINDOW_DAYS, 'cutoff': cutoff, 'catalogue': catalogue, 'tasks': out}
    json.dump(data, open(OUT, 'w'), separators=(',', ':'))
    done = sum(1 for t in out if t['status'] in ('completed', 'closed'))
    pend = sum(1 for t in out if t['status'] == 'pending')
    print("[out] %s (%d bytes) · %d BAU tasks · %d done · %d pending" % (OUT, os.path.getsize(OUT), len(out), done, pend))
    for c in catalogue:
        print("       %-28s %-52s %d" % (c['code'], c['label'], sum(1 for t in out if t['tg'] == c['code'])))

    if '--push' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'bau_data.json'], check=True)
        r = subprocess.run(['git', '-C', REPO, 'commit', '-m', 'Refresh BAU Metrics data'], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode == 0:
            subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True); print("[push] deployed")


if __name__ == '__main__':
    main()
