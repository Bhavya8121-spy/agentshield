import streamlit as st

st.title("🛡️ AgentShield")
st.subheader("Deterministic Firewall for AI Agents")

st.write(
    "Test how AgentShield evaluates and blocks "
    "unsafe AI agent actions."
)

role = st.selectbox(
    "Select role",
    ["reader", "editor", "admin"]
)

prompt = st.text_area(
    "Agent instruction",
    placeholder="Enter an instruction for the agent..."
)

if st.button("Run AgentShield"):
    st.info(
        "Connect this button to your existing "
        "agents.playground.run_agent_demo function."
    )