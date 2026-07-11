import os
from typing import Dict, TypedDict, List
from neo4j import GraphDatabase
from bs4 import BeautifulSoup
import requests
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

load_dotenv()

# 1. ADD NEW FIELDS TO THE STATE
class AgentState(TypedDict):
    raw_notes: str
    gender: str         
    age_category: str    
    extracted_symptoms: List[str]
    matched_diseases: List[Dict]
    clinical_trials: List[Dict]
    web_enrichment: str
    final_report: str

class WorkflowEngine:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0.1)
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
        )

    def ehr_intake_agent(self, state: AgentState) -> Dict:
        prompt = f"Analyze the following clinical notes and extract a clean list of individual medical symptoms. Output ONLY a comma-separated list: {state['raw_notes']}"
        response = self.llm.invoke(prompt)
        
        raw_content = response.content
        if isinstance(raw_content, list):
            raw_content = "".join([block.get("text", "") for block in raw_content if isinstance(block, dict)])
            
        symptoms = [s.strip().lower() for s in raw_content.split(',') if s.strip()]
        return {"extracted_symptoms": symptoms}

    def graph_rag_agent(self, state: AgentState) -> Dict:
        symptoms = state["extracted_symptoms"]
        matched_diseases = []
        
        with self.driver.session() as session:
            result = session.run("""
                MATCH (s:Symptom)-[:INDICATES]->(d:disease)
                WHERE toLower(s.name) IN $symptoms
                WITH d, count(s) as match_count, collect(s.name) as matched_syms
                MATCH (d)-[:MANAGED_BY]->(m:Medication)
                RETURN d.name as disease, match_count, collect(m.name) as medications
                ORDER BY match_count DESC LIMIT 3
            """, symptoms=symptoms)
            
            for record in result:
                matched_diseases.append({
                    "disease": record["disease"],
                    "confidence_score": record["match_count"],
                    "standard_meds": record["medications"]
                })
        return {"matched_diseases": matched_diseases}

    def research_scraper_agent(self, state: AgentState) -> Dict:
        if not state["matched_diseases"]:
            return {"web_enrichment": "No matching index found in internal graph database."}
        
        primary_disease = state["matched_diseases"][0]["disease"]
        url = f"https://pubmed.ncbi.nlm.nih.gov/?term={primary_disease.replace(' ', '+')}"
        
        try:
            res = requests.get(url, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            abstracts = [a.get_text().strip() for a in soup.find_all('a', class_='docsum-title')[:3]]
            enrichment_text = " Recent PubMed Abstracts: " + " | ".join(abstracts)
        except Exception:
            enrichment_text = "Live validation scraping window currently unavailable."
            
        return {"web_enrichment": enrichment_text}

    def trial_matcher_agent(self, state: AgentState) -> Dict:
        diseases = [d["disease"] for d in state["matched_diseases"]]
        matched_trials = []
        
        with self.driver.session() as session:
            result = session.run("""
                MATCH (t:ClinicalTrial)-[:INVESTIGATES]->(d:disease)
                WHERE d.name IN $diseases
                RETURN t.nct_id as nct_id, t.title as title, t.status as status, t.phase as phase, d.name as target_disease
                LIMIT 5
            """, diseases=diseases)
            
            for record in result:
                matched_trials.append({
                    "nct_id": record["nct_id"],
                    "title": record["title"],
                    "status": record["status"],
                    "phase": record["phase"],
                    "target_disease": record["target_disease"]
                })
        return {"clinical_trials": matched_trials}

    # 2. INJECT DEMOGRAPHICS INTO THE SYNTHESIS PROMPT
    def synthesis_agent(self, state: AgentState) -> Dict:
        prompt = f"""
        Synthesize the following information into a structured, formal clinical decision support report:
        
        - Patient Demographics: {state['gender']}, {state['age_category']}
        - Input Symptoms: {state['extracted_symptoms']}
        - GraphRAG Predicted Conditions: {state['matched_diseases']}
        - Live Research Context: {state['web_enrichment']}
        - Matching Experimental Protocols: {state['clinical_trials']}
        
        Provide a detailed breakdown including: Differential Diagnoses, Confident Routing Paths, and Target Trials. 
        Crucially, tailor the warnings, medication suitability, and trial recommendations based on the patient's age category and gender.
        """
        response = self.llm.invoke(prompt)
        
        raw_content = response.content
        if isinstance(raw_content, list):
            raw_content = "".join([block.get("text", "") for block in raw_content if isinstance(block, dict)])
            
        return {"final_report": raw_content}

    def compile_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("intake", self.ehr_intake_agent)
        workflow.add_node("graph_rag", self.graph_rag_agent)
        workflow.add_node("web_scraper", self.research_scraper_agent)
        workflow.add_node("trial_matcher", self.trial_matcher_agent)
        workflow.add_node("synthesis", self.synthesis_agent)
        
        workflow.set_entry_point("intake")
        workflow.add_edge("intake", "graph_rag")
        workflow.add_edge("graph_rag", "web_scraper")
        workflow.add_edge("web_scraper", "trial_matcher")
        workflow.add_edge("trial_matcher", "synthesis")
        workflow.add_edge("synthesis", END)
        
        return workflow.compile()