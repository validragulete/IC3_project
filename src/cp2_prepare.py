import argparse
from pathlib import Path
import re
import sys
import pandas as pd
import numpy as np

FILES = {
    '0': 'baseline_no_anomaly.csv',
    '2': 'bgpclear.csv',
    '4': 'portflaptypes.csv',
}
SKIP = {'time', 'producer', 'encodingpath', 'encoding_path', 'node', 'hostname',
        'device', 'interface', 'source', 'timestamp', 'date', 'label', 'target',
        'experiment', 'incident', 'fault_type'}

def find_csv(root, target):
    matches = [p for p in root.rglob('*') if p.is_file() and (
        p.name.lower() in (target.lower(), target.lower()+'.gz', target.lower()+'.zip'))]
    if not matches:
        raise FileNotFoundError(f'Missing {target}, {target}.gz or {target}.zip under {root}')
    if len(matches) > 1:
        raise ValueError(f'Multiple copies of {target} found: {matches}; keep one')
    return matches[0]

def read_timestamp(s):

    numerical = pd.to_numeric(s, errors='coerce')
    fraction = numerical.notna().mean()
    if fraction >= 0.9:
        median = numerical.abs().median()
        unit = ('ns' if median >= 1e17 else 'us' if median >= 1e14
                else 'ms' if median >= 1e11 else 's')
        return pd.to_datetime(numerical, unit=unit, utc=True, errors='coerce')
    return pd.to_datetime(s, utc=True, errors='coerce')

def infer_features(files, size=60000):

    common = None
    samples = {}
    for exp, filename in files.items():
        sample = pd.read_csv(filename, nrows=size, low_memory=False)
        sample.columns = [str(s).strip() for s in sample.columns]
        if 'time' not in sample.columns:
            raise ValueError(f'No `time` column found in {filename}')
        samples[exp] = sample
        candidates = {c for c in sample.columns if c.lower() not in SKIP}
        common = candidates if common is None else common & candidates
    scored = []
    for col in sorted(common):
        numeric_counts = [pd.to_numeric(samples[e][col], errors='coerce').notna().sum()
                          for e in files]
        if min(numeric_counts) >= 10:
            scored.append((col, sum(numeric_counts)))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [x[0] for x in scored[:12]]

def load_events(path):
    events = pd.read_csv(path, dtype={'experiment':str})
    necessary = {'experiment','start_utc','end_utc','event_type'}
    if not necessary.issubset(events.columns):
        raise ValueError('events.csv needs columns: experiment,start_utc,end_utc,event_type')
    if events.empty:
        raise ValueError('events.csv is empty: transcribe and VERIFY CASE intervals first')
    events = events.loc[events.experiment.isin(['2','4'])].copy()
    events['start'] = pd.to_datetime(events.start_utc, utc=True, errors='raise')
    events['end'] = pd.to_datetime(events.end_utc, utc=True, errors='raise')
    if (events['end'] <= events['start']).any():
        raise ValueError('Each event must have end_utc > start_utc')
    if not all((events.experiment == x).any() for x in ['2','4']):
        raise ValueError('Missing verified events for experiment 2 or 4')
    return events

def aggregate_file(filepath, features, interval, chunksize):
    sums, sums_sq, count, max_values = {}, {}, {}, {}
    for i, chunk in enumerate(pd.read_csv(filepath, chunksize=chunksize, low_memory=False)):
        chunk.columns = [str(x).strip() for x in chunk.columns]
        times = read_timestamp(chunk['time'])
        valid = times.notna()
        if not valid.any():
            continue
        binned = times[valid].dt.floor(interval)
        for name in features:
            vals = pd.to_numeric(chunk.loc[valid, name], errors='coerce')
            tmp = pd.DataFrame({'bin':binned, 'v':vals}).dropna(subset=['v'])
            if tmp.empty:
                continue
            tmp['v2'] = tmp['v']**2
            agg = tmp.groupby('bin').agg(s=('v','sum'), sq=('v2','sum'),
                                          n=('v','count'), maximum=('v','max'))
            for bin_t, row in agg.iterrows():
                key = (bin_t,name)
                sums[key] = sums.get(key,0.0)+float(row['s'])
                sums_sq[key] = sums_sq.get(key,0.0)+float(row['sq'])
                count[key] = count.get(key,0)+int(row['n'])
                max_values[key] = max(max_values.get(key,float('-inf')), float(row['maximum']))
        if i and i % 10 == 0:
            print(f'  {filepath.name}: processed {i * chunksize:,} rows ...', flush=True)

    bins = sorted({k[0] for k in count})
    if not bins:
        raise ValueError(f'No numeric observations for chosen shared metric columns in {filepath}')
    rows=[]
    for b in bins:
        r={'timestamp':b}
        for name in features:
            key=(b,name)
            n=count.get(key,0)
            r[f'{name}__mean']=sums[key]/n if n else np.nan
            r[f'{name}__max']=max_values[key] if n else np.nan
            r[f'{name}__std']=max(0,sums_sq[key]/n-(sums[key]/n)**2)**0.5 if n else np.nan
        rows.append(r)
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser(description='CP2 NetTwin')
    ap.add_argument('--raw',required=True,type=Path,help='Folder containing scenarios 0/2/4 CSV files')
    ap.add_argument('--events',required=True,type=Path,help='Intervals VERIFIED against CASE files')
    ap.add_argument('--out',default='results/cp2_features_10s.csv',type=Path)
    ap.add_argument('--features',default='',help='Comma-separated shared numeric metric column names; autodetect if omitted')
    ap.add_argument('--interval',default='10s')
    ap.add_argument('--chunksize',type=int,default=100000)
    args=ap.parse_args()
    files={exp:find_csv(args.raw,base) for exp,base in FILES.items()}
    events=load_events(args.events)
    features=[x.strip() for x in args.features.split(',') if x.strip()] or infer_features(files)
    if not features:
        raise ValueError('No common numeric metric detected. Specify --features after reviewing Cisco headers.')
    print('Shared numeric metrics:', features)
    outputs=[]
    for exp, path in files.items():
        df=aggregate_file(path,features,args.interval,args.chunksize)
        df['experiment']=exp

        label=np.zeros(len(df),dtype=np.int8)
        event_ids=np.full(len(df),'',dtype=object)
        for ev_number,ev in enumerate(events.loc[events.experiment==exp].itertuples(index=False)):
            overlap=(df['timestamp'] < ev.end) & ((df['timestamp']+pd.Timedelta(args.interval)) > ev.start)
            mask=overlap.to_numpy()
            label[mask]=1
            event_ids[mask]=f'{exp}-CASE-{ev_number:03d}'
        df['event_id']=event_ids
        df['label']=label
        print(f'  Exp {exp}: {len(df):,} bins; {label.sum()} event-overlapping bins')
        outputs.append(df)
    out=pd.concat(outputs,ignore_index=True)
    out['timestamp']=out['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out,index=False)
    print('Saved:',args.out,'total windows:',len(out))

if __name__=='__main__':main()
