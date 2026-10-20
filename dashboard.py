"""AgentShield public-facing benchmark dashboard. Reads saved results only."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results'
st.set_page_config(page_title='AgentShield | Trust, verified', page_icon='🛡️', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width: 1120px; padding-top: 2rem; padding-bottom: 4rem}
h1,h2,h3 {letter-spacing: -.035em}
[data-testid="stMetric"] {background: rgba(128,128,128,.055); border: 1px solid rgba(128,128,128,.14); border-radius: 14px; padding: 16px}
[data-testid="stMetricLabel"] {font-size: .9rem}
small {opacity: .7}
</style>''', unsafe_allow_html=True)

st.caption('AGENTSHIELD  /  AI AGENT RELIABILITY LAB')
st.title('Know what your AI agent will do. Before it does it.')
st.write('Test unsafe tool calls, see what the model proposed, and verify whether the policy firewall prevented unauthorized actions.')

files = sorted(RESULTS.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True) if RESULTS.exists() else []
if not files:
    st.info('No saved benchmarks yet. Run `python -m evaluation.phase4 --mode replay` to generate a local demonstration.')
    st.stop()

live = [p for p in files if p.name.startswith('live_')]
replay = [p for p in files if p.name.startswith('replay_')]
mode = st.segmented_control('Results source', ['Live OCI', 'Synthetic replay'], default='Live OCI' if live else 'Synthetic replay')
choices = live if mode == 'Live OCI' else replay
if not choices:
    st.info('No runs for this mode yet. Use the other mode or generate a new benchmark.')
    st.stop()
selected = st.selectbox('Benchmark run', choices, format_func=lambda p: p.name, label_visibility='collapsed')
try:
    payload = json.loads(selected.read_text())
    rows = payload['rows']
    if not isinstance(rows, list):
        raise ValueError('rows must be a list')
except (OSError, ValueError, KeyError, TypeError) as exc:
    st.error(f'Unable to load benchmark: {type(exc).__name__}')
    st.stop()
if not rows:
    st.warning('This benchmark contains no scenarios.')
    st.stop()

is_live = mode == 'Live OCI'
st.caption(('LIVE MODEL EVALUATION' if is_live else 'DETERMINISTIC SYNTHETIC REPLAY') + f'  ·  {len(rows)} scenarios  ·  {selected.name}')
if not is_live:
    st.info('Replay uses predetermined proposals, not actual model decisions. These scores validate test fixtures and policy behavior only.')

valid = [r for r in rows if r.get('decision') not in ('ERROR', None)]
correct = sum(r.get('policy_correct') is True for r in valid)
blocked = sum(r.get('decision') == 'DENY' for r in rows)
unauthorized = sum(r.get('unauthorized_executed') is True for r in rows)
injection = [r for r in rows if r.get('category') == 'injection']
injection_followed = sum(r.get('injection_followed') is True for r in injection)

c1, c2, c3, c4 = st.columns(4)
c1.metric('Policy checks correct', f'{correct}/{len(valid)}' if valid else '—')
c2.metric('Tool calls blocked', blocked)
c3.metric('Unauthorized executions', unauthorized)
c4.metric('Injection instructions followed', f'{injection_followed}/{len(injection)}' if injection else '—')
st.caption('A blocked action is a policy decision, not proof that the model resisted the attack. Counts reflect this selected run only.')

st.divider()
st.subheader('See the protection in action')
st.write('Pick a scenario to inspect the proposed action and the decision made before tool execution.')
category_labels = {'legitimate':'Legitimate request', 'unauthorized':'Unauthorized request', 'injection':'Prompt injection', 'cross_tenant':'Cross-tenant access'}
category = st.selectbox('Scenario type', list(dict.fromkeys(r.get('category','other') for r in rows)), format_func=lambda v: category_labels.get(v,v.replace('_',' ').title()))
filtered = [r for r in rows if r.get('category') == category]
chosen = st.selectbox('Scenario', filtered, format_func=lambda r: r.get('scenario_id','Unknown scenario'))
proposal = chosen.get('proposal') or {}
left, right = st.columns([1.15, 1])
with left:
    st.markdown('**What the model proposed**' if is_live else '**Fixture tool proposal**')
    st.code(json.dumps(proposal, indent=2), language='json')
with right:
    decision = chosen.get('decision', 'UNKNOWN')
    st.markdown('**What the firewall decided**')
    if decision == 'ALLOW':
        st.success('ALLOWED — ' + str(chosen.get('reason','Authorized')))
    elif decision == 'DENY':
        st.error('BLOCKED — ' + str(chosen.get('reason','Denied')))
    else:
        st.warning(decision + ' — ' + str(chosen.get('reason','No execution')))
    st.write('**Unauthorized side effect:** ' + ('Observed' if chosen.get('unauthorized_executed') else 'Not observed'))
    st.write('**Policy decision correct:** ' + ('Yes' if chosen.get('policy_correct') is True else 'No / not evaluated'))
    if chosen.get('policy_latency_ms') is not None:
        st.caption(f"Policy execution latency: {chosen['policy_latency_ms']} ms (not LLM response time)")

with st.expander('Explore all scenarios and technical evidence'):
    summary = pd.DataFrame([{
        'Scenario': r.get('scenario_id'),
        'Category': r.get('category'),
        'Decision': r.get('decision'),
        'Policy correct': r.get('policy_correct'),
        'Unauthorized execution': r.get('unauthorized_executed'),
        'Latency (ms)': r.get('policy_latency_ms'),
    } for r in rows])
    st.dataframe(summary, hide_index=True, use_container_width=True)
    counts = summary.groupby(['Category', 'Decision']).size().unstack(fill_value=0)
    st.bar_chart(counts)
    st.download_button('Download benchmark evidence (JSON)', data=selected.read_bytes(), file_name=selected.name, mime='application/json')

st.divider()
st.subheader('What this proves — and what it does not')
st.write('AgentShield demonstrates policy enforcement on the tested tool proposals. Live runs additionally measure a model’s behavior on the selected prompts. Results are not a production security certification.')
st.caption('Oracle atomicity applies only to audited execution paths using one shared transaction; live rollback verification and independent security review remain separate requirements.')
