"""Original AgentShield HTML UI hosted through a Streamlit component."""
import os
import logging
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

from agents.playground import build_planner, run_agent_demo, check_agent_output, get_domain, live_available
from agents.planners import PROFILES
from paste_check import check_pasted_proposal
from product_server import check_action

st.set_page_config(page_title="AgentShield", page_icon="🛡️", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container{padding:0!important;max-width:100%!important}
[data-testid="stHeader"],[data-testid="stToolbar"],footer{display:none!important}
iframe{border:0!important}
</style>""", unsafe_allow_html=True)

for key in ("AGENTSHIELD_LIVE","AGENTSHIELD_LIVE_PROVIDER","GEMINI_API_KEY",
            "OCI_COMPARTMENT_OCID","OCI_GENAI_MODEL_ID","OCI_GENAI_ENDPOINT"):
    if key in st.secrets:
        os.environ[key] = str(st.secrets[key])

home = components.declare_component("home", path=str(Path(__file__).parent / "streamlit_frontend"))

def dispatch(req):
    from urllib.parse import urlsplit, parse_qs
    url=req.get("url","")
    method=req.get("method","GET").upper()
    data=req.get("body") or {}
    if method=="GET" and url.startswith("/api/agent/config"):
        domain=get_domain(parse_qs(urlsplit(url).query).get("domain",["ticket"])[0])
        return 200,{"domain":domain.name,"live_available":live_available(),
                    "roles":["reader","editor","admin"],
                    "profiles":[{"id":k,**v} for k,v in PROFILES.items()],
                    "scenarios":domain.scenarios}
    if method!="POST" or not isinstance(data,dict):
        return 400,{"error":"Invalid request"}
    if len(str(data))>20000:
        return 413,{"error":"Request too large"}
    if url=="/api/check":
        return 200,check_action(data["role"],data["action"],data["ticket_id"])
    if url=="/api/paste-check":
        return 200,check_pasted_proposal(data["role"],data["proposal"])
    if url=="/api/v1/check":
        return 200,check_agent_output(role=data["role"],payload=data["payload"],
                    user_request=data.get("user_request"),domain=data.get("domain","ticket"))
    if url=="/api/agent":
        planner=build_planner(data["mode"],data.get("domain","ticket"))
        return 200,run_agent_demo(role=data["role"],prompt=data["prompt"],
                    profile=data["profile"],planner=planner,domain=data.get("domain","ticket"))
    return 404,{"error":"Not found"}

if "reply" not in st.session_state:
    st.session_state.reply=None
if "last_id" not in st.session_state:
    st.session_state.last_id=None

request=home(response=st.session_state.reply,key="agent_home",default=None)
if isinstance(request,dict) and request.get("id")!=st.session_state.last_id:
    st.session_state.last_id=request.get("id")
    try:
        status,data=dispatch(request)
    except (ValueError,TypeError,KeyError) as exc:
        status,data=400,{"error":str(exc)}
    except RuntimeError as exc:
        status,data=503,{"error":str(exc)}
    except Exception:
        logging.exception("AgentShield demo failed")
        status,data=502,{"error":"Agent execution failed. Try the mock agent."}
    st.session_state.reply={"id":request["id"],"status":status,
                            "ok":200<=status<300,"data":data}
    st.rerun()
