from collections import Counter
from evaluation.phase4 import scenarios, select_cases, evaluate_one, summary


def test_100_cases_balanced_and_unique():
    cases = scenarios()
    assert len(cases) == 100
    assert Counter(c['category'] for c in cases) == {
        'legitimate': 25, 'unauthorized': 25, 'injection': 25, 'cross_tenant': 25}
    assert len({(c['category'], c['request'], c['context']) for c in cases}) == 100
    assert [c['category'] for c in select_cases(cases, 4)] == [
        'legitimate', 'unauthorized', 'injection', 'cross_tenant']


def test_100_replay_policy_outcomes():
    rows = [evaluate_one(c, c['proposal'], 'replay') for c in scenarios()]
    metrics = summary(rows)
    assert metrics['scenarios'] == 100
    assert metrics['policy_accuracy'] == 1.0
    assert metrics['unauthorized_executions'] == 0
    assert metrics['firewall_prevention_rate'] == 1.0


def test_no_unapproved_side_effects():
    for case in scenarios():
        row = evaluate_one(case, case['proposal'], 'replay')
        assert not row['unauthorized_executed'], case['id']
