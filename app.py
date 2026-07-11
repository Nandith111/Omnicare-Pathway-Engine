import streamlit as st
from langserve import RemoteRunnable
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="OmniCare Pathway", layout="wide")

st.title("🛡️ OmniCare Pathway Engine")
st.subheader("Agentic Multi-Hop GraphRAG Rare Disease Diagnostic & Trial Matcher")
st.markdown("---")

@st.cache_resource
def load_remote_engine():
    return RemoteRunnable("http://localhost:8000/omnicare")

app_graph = load_remote_engine()

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 📋 Patient Demographics & Intake")
    
    # 1. ADD STREAMLIT WIDGETS FOR DEMOGRAPHICS
    demo_col1, demo_col2 = st.columns(2)
    with demo_col1:
        patient_gender = st.selectbox(
            "Gender Selection",
            options=["Female", "Male", "Non-Binary", "Other/Prefer not to say"]
        )
    with demo_col2:
        patient_age = st.selectbox(
            "Age Category",
            options=[
                "Pediatric (0-17 years)", 
                "Adult (18-64 years)", 
                "Geriatric (65+ years)"
            ]
        )

    sample_text = ("Patient presents with recurring high fever, skin rashes, and severe joint pain. "
                   "Standard anti-inflammatory drugs have yielded little to no improvement over 3 weeks. "
                   "Elevated baseline metabolic fatigue indices present.")
    
    patient_notes = st.text_area(
        "Enter comprehensive patient notes or copy-pasted EHR logs:",
        value=sample_text,
        height=200
    )
    
    submit_btn = st.button("Execute Diagnostic Synthesis Workflow", type="primary")

with col2:
    st.markdown("### ⚙️ Multi-Agent Execution State Tracker")
    if submit_btn and patient_notes:
        with st.spinner("Orchestrating AI Agents via LangServe API..."):
            
            # 2. INJECT WIDGET DATA INTO THE INITIAL STATE PAYLOAD
            initial_state = {
                "raw_notes": patient_notes,
                "gender": patient_gender,      # Captured from UI
                "age_category": patient_age,   # Captured from UI
                "extracted_symptoms": [],
                "matched_diseases": [],
                "clinical_trials": [],
                "web_enrichment": "",
                "final_report": ""
            }
            
            try:
                final_state = app_graph.invoke(initial_state)
                
                symptoms = final_state.get("extracted_symptoms", [])
                trials = final_state.get("clinical_trials", [])
                report = final_state.get("final_report", "No report generated.")
                
                st.info(f"✅ **Intake Agent:** Extracted Symptoms -> {symptoms}")
                st.success(f"🌐 **GraphRAG Agent:** Resolved Multi-Hop Path Matches in Neo4j.")
                st.warning(f"🌐 **Scraper Agent:** Checked external medical registries.")
                st.metric(label="Active Target Clinical Trials Identified", value=len(trials))
                
                st.markdown("### 📝 Synthesized Clinical Decision Report")
                st.write(report)
                
            except Exception as e:
                st.error(f"An error occurred during API execution: {e}")