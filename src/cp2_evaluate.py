import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (f1_score, precision_score, recall_score,
                             classification_report, confusion_matrix)
from sklearn.pipeline import Pipeline

def merged_intervals(e):
    seq=sorted(zip(e.start,e.end))
    merged=[]
    for a,b in seq:
        if merged and a <= merged[-1][1]:
            merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else:
            merged.append((a,b))
    return merged

def temporal_split(df, events, embargo='60s'):
    td=pd.Timedelta(embargo)
    assigned=[]
    for exp, group in df.groupby('experiment',sort=False):
        grp=group.sort_values('timestamp').copy()
        n=len(grp)
        if n<30:
            raise ValueError(f'Experiment {exp}: only {n} time bins')
        ev=events.loc[events.experiment.eq(exp)]
        if ev.empty:
            t1=grp.iloc[int(0.60*n)].timestamp
            t2=grp.iloc[int(0.80*n)].timestamp
        else:
            clusters=merged_intervals(ev)
            m=len(clusters)
            if m<3:
                raise ValueError(f'Experiment {exp}: fewer than 3 disjoint CASE groups')
            i1=max(1,min(m-2,round(0.60*m)))
            i2=max(i1+1,min(m-1,round(0.80*m)))
            t1=clusters[i1-1][1]+(clusters[i1][0]-clusters[i1-1][1])/2
            t2=clusters[i2-1][1]+(clusters[i2][0]-clusters[i2-1][1])/2
        grp['split']=''
        grp.loc[grp.timestamp < t1-td, 'split']='train'
        grp.loc[(grp.timestamp >= t1+td) & (grp.timestamp<t2-td), 'split']='val'
        grp.loc[grp.timestamp >= t2+td,'split']='test'
        print(f'{exp}: boundaries {t1} / {t2}; clusters {len(merged_intervals(ev)) if not ev.empty else 0}')
        assigned.append(grp)
    return pd.concat(assigned).sort_index().query('split != ""').copy()

def describe(y_true,y_pred):
    return {
      'macro_f1':float(f1_score(y_true,y_pred,labels=[0,1],average='macro',zero_division=0)),
      'anomaly_precision':float(precision_score(y_true,y_pred,pos_label=1,zero_division=0)),
      'anomaly_recall':float(recall_score(y_true,y_pred,pos_label=1,zero_division=0)),
      'anomaly_f1':float(f1_score(y_true,y_pred,pos_label=1,zero_division=0)),
      'confusion_matrix_TN_FP_FN_TP':confusion_matrix(y_true,y_pred,labels=[0,1]).ravel().tolist(),
      'support': {'normal':int(sum(y_true==0)),'anomaly':int(sum(y_true==1))},
    }

def run_model(train,val,test,feature_cols,model):
    X_train=train[feature_cols];X_val=val[feature_cols];X_test=test[feature_cols]
    model.fit(X_train,train.label)
    return {'validation':describe(val.label.to_numpy(),model.predict(X_val)),
            'test':describe(test.label.to_numpy(),model.predict(X_test))}

def main():
    ap=argparse.ArgumentParser(description='CP2 NetTwin')
    ap.add_argument('--input',default='results/cp2_features_10s.csv',type=Path)
    ap.add_argument('--output',default='results/cp2_metrics.json',type=Path)
    ap.add_argument('--embargo',default='60s')
    ap.add_argument('--events',required=True,type=Path)
    args=ap.parse_args()
    df=pd.read_csv(args.input,dtype={'experiment':str})
    mandatory={'timestamp','experiment','label'}
    if not mandatory.issubset(df.columns):
        raise ValueError(f'Missing columns: {mandatory-set(df.columns)}')
    df['timestamp']=pd.to_datetime(df.timestamp,utc=True)
    if not set(df.label.unique()).issubset({0,1}):
        raise ValueError('label must be binary (0=normal, 1=CASE overlap)')
    features=[c for c in df.columns if c not in mandatory and pd.api.types.is_numeric_dtype(df[c])]
    if not features:raise ValueError('No numeric features available')

    df=df.sort_values(['experiment','timestamp']).reset_index(drop=True)
    for f in features:
        df[f+'_last60_mean']=df.groupby('experiment',sort=False)[f].transform(
            lambda s:s.rolling(6,min_periods=1).mean())
    features60=[f+'_last60_mean' for f in features]
    ev=pd.read_csv(args.events,dtype={'experiment':str})
    ev['start']=pd.to_datetime(ev.start_utc,utc=True)
    ev['end']=pd.to_datetime(ev.end_utc,utc=True)
    df=temporal_split(df,ev,args.embargo)

    removed_cross_split_events=[]
    if 'event_id' in df.columns:
        df['event_id']=df['event_id'].fillna('')
        positive=df.loc[df.label.eq(1) & df.event_id.ne('')]
        event_splits=positive.groupby('event_id')['split'].nunique()
        removed_cross_split_events=event_splits.index[event_splits.gt(1)].tolist()
        if removed_cross_split_events:
            print('Removed cross-split CASE events:',removed_cross_split_events)
            df=df.loc[~df.event_id.isin(removed_cross_split_events)].copy()
    train,val,test=[df.loc[df.split==x].copy() for x in ['train','val','test']]
    if min(len(train),len(val),len(test))==0:
        raise ValueError('A split is empty after embargo; reduce embargo or review sampling')
    summary={p: {str(int(k)):int(v) for k,v in g.label.value_counts().items()}
             for p,g in [('train',train),('val',val),('test',test)]}
    if len(train.label.unique())<2:
        raise ValueError('Train has just one class. Reconsider event-aware splitting; do NOT fabricate metrics.')
    if val.label.sum()==0 or test.label.sum()==0:
        raise ValueError('No anomaly in val/test after temporal split. Current F1 would be misleading. '
                         'Use additional Cisco sessions and verified event-aware splits.')
    def rf():
        return Pipeline([('imputer',SimpleImputer(strategy='median',add_indicator=True)),
                         ('rf',RandomForestClassifier(n_estimators=200,max_depth=8,
                                                      min_samples_leaf=3,class_weight='balanced',
                                                      n_jobs=-1,random_state=42))])
    results={
      'method':'Chronological CASE-event-aware 60/20/20 by merged incident groups in each incident experiment; 60s embargo; normal experiment split 60/20/20 by time',
      'counts':summary,
      'removed_cross_split_events':removed_cross_split_events,
      'features_10s':features,
      'baseline_majority':run_model(train,val,test,features,DummyClassifier(strategy='most_frequent')),
      'RF_10s':run_model(train,val,test,features,rf()),
      'RF_60s_causal':run_model(train,val,test,features60,rf()),
      'limitations':['Same-session temporal evaluation, not cross-session generalization',
                     'CASE event windows are only a proxy for measured operational impact',
                     'All hyperparameter selection must use validation, not test',
                     'No MPLS L2VPN/L3VPN impact inference'],
    }
    args.output.parent.mkdir(exist_ok=True,parents=True)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    print('Saved:',args.output)

if __name__=='__main__':main()
