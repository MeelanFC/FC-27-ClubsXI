import testenv  # noqa: F401  (test settings, must come first)
import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('selection_backtest',ROOT/'tools/selection_backtest.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def game(index,person='p',build='6'):
    return dict(id=str(index),club='club',timestamp=index,gf=index%3,ga=1,
                tokens=[[person,'midfielder',build],['q','defender','3']],
                players=[dict(person_id=person,band='midfielder',
                    stats=dict(goals=index%3,assists=0,passes_made=12,tackles_made=2,shots=3),
                    decoded=dict(interceptions=2,second_assists=0))],
                opponent_id='opp'+str(index),opponent=dict(real_human_count=5),
                excluded_appearances=[])


def test_future_matches_cannot_change_earlier_predictions():
    games=[game(i) for i in range(5)]
    before=module.backtest(games)['predictions']
    future=game(10)
    future['gf']=1000
    after=module.backtest(games+[future])['predictions']
    assert before==after[:len(before)]


def test_same_match_stats_and_outcome_do_not_enter_features():
    train=[game(i) for i in range(3)]
    target=game(4)
    before=module.predict(train,target,'contributions',10.)
    target['gf']=1000
    target['players'][0]['stats']['goals']=1000
    after=module.predict(train,target,'contributions',10.)
    assert before==after


def test_different_club_cannot_enter_training():
    games=[game(i) for i in range(4)]
    foreign=game(-1)
    foreign['club']='other'
    foreign['gf']=1000
    assert module.backtest(games)['predictions']==module.backtest(games+[foreign])['predictions']


def test_same_timestamp_is_not_earlier_training():
    games=[game(i) for i in range(4)]
    twin=game(3,'new')
    twin['id']='twin'
    rows=module.backtest(games+[twin])['predictions']
    assert len(rows)==2
    assert all(row['train_matches']==['0','1','2'] for row in rows)


def test_replacement_contrast_requires_unchanged_remaining_builds():
    first=game(0)
    second=game(1,'replacement')
    assert len(module.contrasts([first,second]))==1
    second['tokens'][1][2]='4'
    assert module.contrasts([first,second])==[]
