import os
import pandas as pd
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

class DataIngector:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
        )

    def close(self):
        self.driver.close()

    def init_constraints(self):
        with self.driver.session() as session:
            # Existing constraints
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:disease) REQUIRE d.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:Symptom) REQUIRE s.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:ClinicalTrial) REQUIRE t.nct_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (i:Intervention) REQUIRE i.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:Medication) REQUIRE m.name IS UNIQUE")
            
            # New constraints for lifestyle and metadata
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Precaution) REQUIRE p.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (w:Workout) REQUIRE w.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (diet:Diet) REQUIRE diet.name IS UNIQUE")

    def ingest_sympscan(self, main_csv_path, meds_csv_path):
        self.init_constraints()
        
        # 1. BATCH INGEST SYMPTOMS
        df = pd.read_csv(main_csv_path)
        symptom_cols = [col for col in df.columns if col != 'diseases']
        
        symptom_records = []
        for _, row in df.iterrows():
            disease = row['diseases'].strip()
            for sym in symptom_cols:
                if row[sym] == 1:
                    clean_sym = sym.replace("_", " ").strip()
                    symptom_records.append({"disease": disease, "symptom": clean_sym})

        with self.driver.session() as session:
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.disease})
                MERGE (s:Symptom {name: record.symptom})
                MERGE (s)-[:INDICATES]->(d)
            """, records=symptom_records)

        # 2. BATCH INGEST MEDICATIONS
        df_meds = pd.read_csv(meds_csv_path)
        med_records = []
        for _, row in df_meds.iterrows():
            disease = row['Disease'].strip()
            meds = [m.strip() for m in str(row['Medication']).split(',')]
            for med in meds:
                if med:
                    med_records.append({"disease": disease, "medication": med})

        with self.driver.session() as session:
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.disease})
                MERGE (m:Medication {name: record.medication})
                MERGE (d)-[:MANAGED_BY]->(m)
            """, records=med_records)
            
        print("Successfully batched and ingested SympScan Knowledge Base Graph.")

    def ingest_lifestyle_and_metadata(self, desc_path, prec_path, work_path, diet_path):
        with self.driver.session() as session:
            # 1. INGEST DESCRIPTIONS (As properties on the disease node)
            df_desc = pd.read_csv(desc_path)
            desc_records = [{"disease": row['Disease'].strip(), "desc": str(row['Description']).strip()} 
                            for _, row in df_desc.iterrows() if pd.notna(row['Description'])]
            
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.disease})
                SET d.description = record.desc
            """, records=desc_records)
            print("Successfully attached Disease Descriptions.")

            # 2. INGEST PRECAUTIONS
            df_prec = pd.read_csv(prec_path)
            prec_records = []
            for _, row in df_prec.iterrows():
                disease = row['Disease'].strip()
                for col in ['Precaution_1', 'Precaution_2', 'Precaution_3', 'Precaution_4']:
                    if pd.notna(row[col]):
                        prec = str(row[col]).strip()
                        if prec:
                            prec_records.append({"disease": disease, "precaution": prec})
            
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.disease})
                MERGE (p:Precaution {name: record.precaution})
                MERGE (d)-[:HAS_PRECAUTION]->(p)
            """, records=prec_records)
            print("Successfully linked Precautions.")

            # 3. INGEST WORKOUTS
            df_work = pd.read_csv(work_path)
            work_records = []
            for _, row in df_work.iterrows():
                if pd.notna(row['Disease']) and pd.notna(row['Workouts']):
                    work_records.append({
                        "disease": str(row['Disease']).strip(), 
                        "workout": str(row['Workouts']).strip()
                    })
            
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.disease})
                MERGE (w:Workout {name: record.workout})
                MERGE (d)-[:RECOMMENDS_WORKOUT]->(w)
            """, records=work_records)
            print("Successfully linked Workouts.")

            # 4. INGEST DIETS
            df_diet = pd.read_csv(diet_path)
            diet_records = []
            for _, row in df_diet.iterrows():
                if pd.notna(row['Disease']) and pd.notna(row['Diet']):
                    diet_records.append({
                        "disease": str(row['Disease']).strip(), 
                        "diet": str(row['Diet']).strip()
                    })
            
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.disease})
                MERGE (diet:Diet {name: record.diet})
                MERGE (d)-[:RECOMMENDS_DIET]->(diet)
            """, records=diet_records)
            print("Successfully linked Diets.")

    def ingest_clinical_trials(self, trials_csv_path):
        df = pd.read_csv(trials_csv_path)
        trial_records = []
        condition_links = []
        intervention_links = []
        
        # Prepare all data locally in Python first
        for _, row in df.iterrows():
            nct_id = str(row['nct_id']).strip()
            trial_records.append({
                "nct_id": nct_id,
                "title": str(row.get('title', '')),
                "status": str(row.get('status', '')),
                "phase": str(row.get('phase', '')),
                "summary": str(row.get('brief_summary', '')),
                "country": str(row.get('country', ''))
            })
            
            conditions = [c.strip() for c in str(row.get('condition', '')).split(';') if c.strip()]
            for cond in conditions:
                condition_links.append({"nct_id": nct_id, "condition": cond})
                
            interventions = [i.strip() for i in str(row.get('intervention', '')).split(';') if i.strip()]
            for inter in interventions:
                intervention_links.append({"nct_id": nct_id, "intervention": inter})

        with self.driver.session() as session:
            # Create Trials
            session.run("""
                UNWIND $records AS record
                MERGE (t:ClinicalTrial {nct_id: record.nct_id})
                SET t.title = record.title, t.status = record.status, 
                    t.phase = record.phase, t.summary = record.summary, 
                    t.country = record.country
            """, records=trial_records)
            
            # Link Conditions
            session.run("""
                UNWIND $records AS record
                MERGE (d:disease {name: record.condition})
                MATCH (t:ClinicalTrial {nct_id: record.nct_id})
                MERGE (t)-[:INVESTIGATES]->(d)
            """, records=condition_links)
            
            # Link Interventions
            session.run("""
                UNWIND $records AS record
                MERGE (i:Intervention {name: record.intervention})
                MATCH (t:ClinicalTrial {nct_id: record.nct_id})
                MERGE (t)-[:TESTS]->(i)
            """, records=intervention_links)
            
        print("Successfully batched and ingested Global Clinical Trials Dataset.")

if __name__ == "__main__":
    injector = DataIngector()
    
    # 1. Base Graph (Diseases, Symptoms, Medications)
    injector.ingest_sympscan("Diseases_and_Symptoms_dataset.csv", "medications.csv")
    
    # 2. Lifestyle & Metadata Extensions
    injector.ingest_lifestyle_and_metadata("description.csv", "precautions.csv", "workout.csv", "diets.csv")
    
    # 3. Clinical Trials (Currently disabled based on your previous action)
    injector.ingest_clinical_trials("clinical_trials_2025_2026.csv")
    
    injector.close()