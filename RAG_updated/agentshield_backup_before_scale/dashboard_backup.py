"""Local-only dashboard of saved synthetic benchmark results."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='AgentShield Reliability Lab', layout='wide')
st.title('AgentShield | Reliability Lab')
st.caption('Synthetic scenarios. Replay metrics do not measure LLM reliability; live metrics depend on model and prompts.')
files = sorted((ROOT / 'results').glob('*.json'), reverse=True)
if not files:
    st.info('Run: python -m evaluation.phase4 --mode replay')
    st.stop()
selected = st.selectbox('Benchmark run', files, format_func=lambda p: p.name)
rows = json.loads(selected.read_text())['rows']
frame = pd.DataFrame([{k: v for k, v in row.items() if k != 'proposal'} for row in rows])
a, b, c, d = st.columns(4)
a.metric('Scenarios', len(rows))
b.metric('Correct policy decisions', int(frame['policy_correct'].sum()))
c.metric('Unauthorized executions', int(frame['unauthorized_executed'].sum()))
d.metric('Model proposals of unsafe tools', sum(r['expected'] == 'DENY' and r['proposal'].get('tool') in {'delete_ticket','update_ticket'} for r in rows))
st.subheader('Outcomes by category')
st.dataframe(frame.groupby(['category', 'decision']).size().reset_index(name='count'), use_container_width=True)
st.subheader('Scenario traces')
st.dataframe(frame, use_container_width=True)
selected_id = st.selectbox('Inspect proposal', [r['scenario_id'] for r in rows])
st.json(next(r for r in rows if r['scenario_id'] == selected_id))
st.info(
    "Oracle transaction safety: ticket mutations and audit records "
    "are committed together when executed through the new "
    "audited_execute() path. Direct store operations may still "
    "commit independently. Live rollback behavior has not yet "
    "been verified against Oracle."
)
