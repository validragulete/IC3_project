"""CP1 NetTwin: streaming CSV audit, no PNETLab required."""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

TIME_HINTS = ('timestamp', 'datetime', 'date_time', 'sample_time', 'time_stamp')

def find_time_column(fields):
    preferred = [f for f in fields if any(h in f.lower().replace(' ', '_') for h in TIME_HINTS)]
    if preferred:
        return preferred[0]
    possible = [f for f in fields if f.lower().strip() in ('time', 'date')]
    return possible[0] if possible else None

def to_time(s):
    if not s or not s.strip():
        return None
    s = s.strip()
    if s.isdecimal() and len(s) in (10, 13, 16, 19):
        try:
            return datetime.fromtimestamp(int(s) / {10:1, 13:1000, 16:1_000_000, 19:1_000_000_000}[len(s)], tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None

def inspect(path):
    missing = Counter()
    rows = 0
    seen_times = set()
    duplicate_times = 0
    min_t = max_t = last = None
    intervals = []
    with path.open('r', encoding='utf-8-sig', errors='replace', newline='') as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
        except csv.Error:
            delimiter = ','
        reader = csv.DictReader(fh, delimiter=delimiter)
        fields = reader.fieldnames or []
        if not fields:
            return {'file':str(path),'error':'Empty CSV or missing header'}
        tcol = find_time_column(fields)
        for record in reader:
            rows += 1
            for f in fields:
                value = record.get(f)
                if value is None or value.strip() == '' or value.strip().lower() in ('nan', 'null', 'none'):
                    missing[f] += 1
            if tcol:
                stamp = to_time(record.get(tcol) or '')
                if stamp is not None:
                    if stamp in seen_times:
                        duplicate_times += 1
                    if len(seen_times) < 300000:
                        seen_times.add(stamp)
                    if last is not None:
                        try:
                            delta = (stamp-last).total_seconds()
                            if delta > 0 and len(intervals) < 100000:
                                intervals.append(delta)
                        except TypeError:
                            pass
                    last = stamp
                    try:
                        min_t = stamp if min_t is None or stamp < min_t else min_t
                        max_t = stamp if max_t is None or stamp > max_t else max_t
                    except TypeError:
                        pass
    return {'file':str(path),'rows':rows,'columns':len(fields),'column_names':fields,
            'missing_by_column':dict(missing),'timestamp_column':tcol,
            'first_timestamp':min_t.isoformat() if min_t else None,
            'last_timestamp':max_t.isoformat() if max_t else None,
            'median_positive_consecutive_interval_seconds':median(intervals) if intervals else None,
            'repeated_timestamps_observed':duplicate_times,
            'notes':'Resolution estimate is per-row, not per-device; repeated timestamps may be expected across devices.'}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input',default='data/raw')
    p.add_argument('--output',default='results')
    args = p.parse_args()
    root = Path(args.input)
    out = Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    files = sorted(root.rglob('*.csv'))
    if not files:
        raise SystemExit(f'ERROR: no CSV found under {root.resolve()}. Download and extract Cisco dataset CSV files first.')
    reports = []
    for file in files:
        print('Inspecting:',file)
        reports.append(inspect(file))
    (out/'audit.json').write_text(json.dumps(reports, indent=2,ensure_ascii=False),encoding='utf-8')
    lines = ['# NetTwin CP1 — raport de audit al datelor','','Generat automat din CSV-urile locale.','',
             '| CSV | Randuri | Coloane | Prima observatie | Ultima observatie | Interval median pozitiv (s) |',
             '|---|---:|---:|---|---|---:|']
    for r in reports:
        if r.get('error'):
            lines.append(f"| {Path(r['file']).name} | EROARE: {r['error']} | | | | |")
        else:
            interval = r['median_positive_consecutive_interval_seconds']
            lines.append(f"| {Path(r['file']).name} | {r['rows']} | {r['columns']} | {r['first_timestamp'] or 'neidentificat'} | {r['last_timestamp'] or 'neidentificat'} | {interval if interval is not None else 'neidentificat'} |")
    lines.extend(['','## Goluri pe coloane',''])
    for r in reports:
        if 'error' in r: continue
        lines.extend([f"### {Path(r['file']).name}",f"Total: {r['rows']} randuri, {r['columns']} coloane.",
                      f"Coloana timestamp detectata: `{r['timestamp_column']}`."])
        if r['missing_by_column']:
            for col,n in sorted(r['missing_by_column'].items(),key=lambda x:-x[1]):
                lines.append(f'- `{col}`: {n} valori lipsa ({100*n/max(1,r["rows"]):.2f}%)')
        else: lines.append('- Nu au fost detectate celule goale / NA textual.')
        lines.append('')
    lines.extend(['## Important','','Unitatile fizice se verifica in **header definition** Cisco, nu se deduc din numele coloanei.',
                  'Split propus: pe sesiuni/experimente distincte, temporal, pentru a evita leakage; in CP1 nu se antreneaza model.',
                  'Fisierele CASE trebuie inspectate separat pentru etichetarea incidentelor.'])
    (out/'audit_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'OK: {len(files)} CSV inspected. Outputs: {out}/audit.json and {out}/audit_report.md')

if __name__=='__main__': main()
