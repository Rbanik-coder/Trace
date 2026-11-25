"""Supervised mule-risk demo model trained on reproducible synthetic data.
This is a hackathon prototype, not a validated banking/forensic model."""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

FEATURES = ['incoming_count','outgoing_count','incoming_amount','outgoing_amount','counterparty_count','median_hold_hours','rapid_outgoing_ratio','night_activity_ratio','fan_in_ratio','fan_out_ratio']

def train_demo_model(seed=42, n=5000):
    rng=np.random.default_rng(seed)
    y=rng.binomial(1,0.28,n)
    X=np.zeros((n,len(FEATURES)))
    for i,label in enumerate(y):
        if label:
            X[i]=[rng.integers(5,35),rng.integers(4,30),rng.uniform(50000,900000),rng.uniform(45000,880000),rng.integers(6,30),rng.uniform(.05,3),rng.uniform(.55,1),rng.uniform(.25,.9),rng.uniform(.55,1),rng.uniform(.5,1)]
        else:
            X[i]=[rng.integers(0,12),rng.integers(0,12),rng.uniform(0,160000),rng.uniform(0,150000),rng.integers(0,12),rng.uniform(3,240),rng.uniform(0,.35),rng.uniform(0,.35),rng.uniform(0,.45),rng.uniform(0,.45)]
    Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=.25,random_state=seed,stratify=y)
    model=RandomForestClassifier(n_estimators=180,max_depth=9,min_samples_leaf=3,class_weight='balanced',random_state=seed,n_jobs=-1)
    model.fit(Xtr,ytr); pred=model.predict(Xte)
    metrics={'accuracy':round(accuracy_score(yte,pred),3),'precision':round(precision_score(yte,pred,zero_division=0),3),'recall':round(recall_score(yte,pred,zero_division=0),3),'f1':round(f1_score(yte,pred,zero_division=0),3),'train_rows':len(ytr),'test_rows':len(yte)}
    return model,metrics

MODEL,METRICS=train_demo_model()

def predict(features):
    row=np.array([[float(features.get(k,0)) for k in FEATURES]])
    p=float(MODEL.predict_proba(row)[0][1])
    return round(p*100,1), dict(zip(FEATURES,MODEL.feature_importances_))
