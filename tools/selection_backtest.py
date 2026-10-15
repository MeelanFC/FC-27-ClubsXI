"""Exploratory chronological evaluation, not an approved selection engine.

Requires NumPy in the analysis environment; the viewer gains no dependency.
Each held-out prediction uses only strictly earlier matches from that club.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path

import numpy as np


def tokens(game):
    return {tuple(t) for t in game['tokens']}


def contrasts(games):
    results = []
    for left, right in combinations(games, 2):
        if left['club'] != right['club'] or left['id'] == right['id']:
            continue
        a, b = tokens(left), tokens(right)
        removed, added = a-b, b-a
        if len(removed) != 1 or len(added) != 1:
            continue
        out, into = next(iter(removed)), next(iter(added))
        results.append({
            'club':left['club'], 'matches':[left['id'],right['id']],
            'before':out,'after':into,'same_band':out[1]==into[1],
            'kind':'same person, changed build/position' if out[0]==into[0] else 'different person',
            'unchanged_full_appearance_tokens':sorted(a&b),
            'team_scores':[[left['gf'],left['ga']],[right['gf'],right['ga']]],
            'opponents':[left['opponent_id'],right['opponent_id']],
            'opponent_humans':[left['opponent']['real_human_count'],right['opponent']['real_human_count']],
            'omitted_appearances':[left['excluded_appearances'],right['excluded_appearances']],
            'interpretation':'Other qualifying teammates/builds unchanged; opponents, '
                'match conditions and omitted appearances may differ. Not a causal test.'})
    return results


def features(game, mode, prior_games=()):
    # The retrospective question assumes the eventual lineup is known. No
    # same-match results, personal performance, or post-match ratings enter X.
    result = {'our_humans':len(game['tokens'])/11,
              'opponent_humans':game['opponent']['real_human_count']/11}
    if mode in ('history','contributions'):
        history = game['opponent'].get('prior_played_matches',[])
        # Prior history was collected retrospectively: timestamps establish event
        # order, not that the collector possessed this information at the time.
        history = [g for g in history if g['match_timestamp']<game['timestamp']]
        result['opponent_history_missing'] = float(not history)
        if history:
            result['opponent_prior_gd'] = sum(g['goals_for']-g['goals_against'] for g in history)/len(history)
        if mode == 'history':
            return result
    if mode == 'context':
        return result
    members = sorted(tokens(game))
    for member in members:
        key = member[0] if mode == 'people' else '|'.join(member)
        result['member:'+key] = 1.
    if mode == 'pairs':
        for a,b in combinations(members,2):
            result['pair:'+'|'.join(a)+'/'+ '|'.join(b)] = 1.
    if mode == 'contributions':
        # Use only previous same-club appearances in the candidate's broad band.
        # Never use the held-out match's individual stats to predict its outcome.
        fields = ('goals','assists','passes_made','tackles_made','shots')
        totals = defaultdict(float)
        known = 0
        for person,band,_build in members:
            appearances = [p for g in prior_games if g['club']==game['club']
                           and g['timestamp']<game['timestamp'] for p in g['players']
                           if p['person_id']==person and p['band']==band]
            if not appearances:
                continue
            known += 1
            for field in fields:
                vals = [p['stats'][field] for p in appearances if p['stats'][field] is not None]
                if vals:
                    totals[field] += sum(vals)/len(vals)
            for field in ('interceptions','second_assists'):
                vals = [p['decoded'][field] for p in appearances if p['decoded'][field] is not None]
                if vals:
                    totals[field] += sum(vals)/len(vals)
        result['prior_contributions_coverage'] = known/max(len(members),1)
        for field,value in totals.items():
            result['prior:'+field] = value/max(known,1)
    return result


def predict(train, test, mode, alpha):
    rows = [features(g,mode,train) for g in train]
    vocabulary = sorted(set().union(*(r.keys() for r in rows)))
    x = np.array([[r.get(k,0.) for k in vocabulary] for r in rows])
    r = features(test,mode,train)
    xt = np.array([r.get(k,0.) for k in vocabulary])
    y = np.array([[g['gf'],g['ga']] for g in train],dtype=float)
    center, mean = x.mean(axis=0), y.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale<1e-12] = 1.
    xc = (x-center)/scale
    # Dual ridge solve is small even when pair vocabulary is large.
    weights = np.linalg.solve(xc@xc.T+alpha*np.eye(len(train)), y-mean)
    return (mean+((xt-center)/scale)@xc.T@weights).tolist()


def backtest(games):
    predictions = []
    for game in sorted(games,key=lambda g:(g['timestamp'],g['id'],g['club'])):
        train = [g for g in games if g['club']==game['club']
                 and g['timestamp']<game['timestamp'] and g['id']!=game['id']]
        if len(train)<3:
            continue
        baseline = [sum(g[key] for g in train)/len(train) for key in ('gf','ga')]
        candidates = {'club_mean':baseline}
        for mode in ('context','people','builds','pairs','history','contributions'):
            for alpha in (1.,10.,100.):
                candidates[mode+':'+str(alpha)] = predict(train,game,mode,alpha)
        predictions.append({'match':game['id'],'club':game['club'],
            'timestamp':game['timestamp'],'train_matches':[g['id'] for g in train],
            'actual':[game['gf'],game['ga']],'predictions':candidates})
    buckets = defaultdict(list)
    for row in predictions:
        for model,pred in row['predictions'].items():
            for club in (row['club'],'all'):
                buckets[(club,model)].append((pred,row['actual']))
    summary = []
    for (club,model), rows in sorted(buckets.items()):
        n = len(rows)
        summary.append({'club':club,'model':model,'test_games':n,
            'goal_difference_mae':sum(abs((p[0]-p[1])-(a[0]-a[1])) for p,a in rows)/n,
            'goals_for_mae':sum(abs(p[0]-a[0]) for p,a in rows)/n,
            'goals_against_mae':sum(abs(p[1]-a[1]) for p,a in rows)/n})
    return {'method':'Expanding strictly earlier same-club training; 3-game warmup; '
            'fixed ridge penalties. Model comparison is exploratory, not independent '
            'validation of a winner chosen after seeing these results.',
            'limits':['Retrospective full-appearance lineup is assumed known.',
                      'Opponent human count is context, not opponent quality.',
                      'No causal chemistry interpretation.',
                      'The contributions variant uses only strictly earlier same-club '
                      'broad-band personal contributions; exact historical tactical jobs are unknown.',
                      'Opponent historical matches were often collected after the target '
                      'match. This is a retrospective replay, not a live deployment backtest.'],
            'summary':summary,'predictions':predictions,'replacement_contrasts':contrasts(games)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('data/selection-backtest.json'))
    args=parser.parse_args()
    report=backtest(json.loads(args.input.read_text(encoding='utf-8'))['matches'])
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('One-token replacement comparisons:',len(report['replacement_contrasts']))
    for r in report['summary']:
        if r['club']=='all':
            print(r['model'],r['test_games'],round(r['goal_difference_mae'],3))


if __name__=='__main__':
    main()
