from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pandas as pd
import numpy as np
import os
import json
from groq import Groq
from dotenv import load_dotenv

# Ensure .env is loaded
load_dotenv()

class MLModel:
    """
    ML-Assisted Extraction and Candidate Matching Model.
    
    Uses TF-IDF for similarity matching and Groq/Qwen for structured data extraction.
    NO predictive models for cost or time. Final evaluation is deterministic rule-based.
    """
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words='english')
        self.boq_df = None
        self.tfidf_matrix = None
        self.is_fitted = False
        
        # Initialize Groq Client for OCR/NLP extraction
        self.groq_client = None
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                self.groq_client = Groq(api_key=groq_key)
            except Exception as e:
                print(f"Error creating Groq client: {e}")
        else:
            print("Warning: GROQ_API_KEY is missing from environment")

    def fit_boq(self, boq_items):
        """Fit TF-IDF vectorizer on BOQ descriptions for similarity matching."""
        if not boq_items: 
            return
        self.boq_df = pd.DataFrame(boq_items)
        self.tfidf_matrix = self.vectorizer.fit_transform(self.boq_df['description'])
        self.is_fitted = True

    def find_similar_items(self, description, top_n=3):
        """
        Find similar BOQ items using TF-IDF cosine similarity.
        Returns list of candidates with similarity scores for rate source matching.
        """
        if self.tfidf_matrix is None or not self.is_fitted:
            return []
        
        try:
            query_vec = self.vectorizer.transform([description])
            similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
            best_match_indices = similarities.argsort()[-top_n:][::-1]
            
            results = []
            for idx in best_match_indices:
                if similarities[idx] > 0.1:
                    item = self.boq_df.iloc[idx].to_dict()
                    item['similarity_score'] = float(similarities[idx])
                    results.append(item)
            return results
        except Exception as e:
            print(f"Similarity search error: {e}")
            return []
    
    def find_similar_item(self, description, top_n=1):
        """Backward compatibility wrapper - returns first item or None"""
        items = self.find_similar_items(description, top_n=top_n)
        return items[0] if items else None

    def parse_instruction(self, text, project_context=None, chat_history=None, session_metadata=None):
        """
        Extract structured data from user input using Groq/Qwen.
        Returns extraction-only JSON (NO predictions or calculations).
        Final cost/time evaluation requires human confirmation via separate rule-based engine.
        """
        context_str = f"\nPROJECT BOQ CONTEXT (Samples):\n{project_context}" if project_context else ""
        history_str = ""
        if chat_history:
            history_str = "\nCONVERSATION HISTORY:\n" + "\n".join([f"{m['role'].upper()}: {m['content']}" for m in chat_history[-10:]])
        
        session_state = session_metadata or {}
        variation_type = session_state.get('variation_type')
        collected_details = session_state.get('collected_details', {})
        
        if not variation_type:
            # Step 1: Variation Type Selection
            prompt = f"""
You are an Expert AI Quantity Surveyor (QS) and Variation Assistant.
Your role: EXTRACT DATA ONLY. NO cost/time predictions. Final evaluation is deterministic rule-based.

User Query: "{text}"
{history_str}
{context_str}

WORKFLOW STATE: Variation Type Selection

Instructions:
1. If the user is asking about a variation or change, guide them to select a FIDIC variation type.
2. Present the 6 FIDIC variation types clearly:
   - Type 1: Quantity Changes
   - Type 2: Quality/Characteristics Changes
   - Type 3: Levels/Positions/Dimensions Changes
   - Type 4: Omission of Work
   - Type 5: Additional Work/Plant/Materials
   - Type 6: Sequence/Timing Changes
3. Ask the user to select which type best describes their variation.
4. If the user's query clearly indicates a specific type, suggest it and ask for confirmation.
5. Map the type to the evaluation mode only for extraction labels, not for final calculation:
    - TYPE1 -> quantity_change
    - TYPE2 -> substitution when the user says change X to Y, otherwise capture as a quality change needing human review
    - TYPE4 -> omission
    - TYPE5 -> additional_work
    - TYPE6 -> time_sequence_change

MANDATORY JSON Output Format:
{{
    "reply": "Your natural language response",
    "workflow_state": "type_selection",
    "variation_type": "TYPE1" | "TYPE2" | "TYPE3" | "TYPE4" | "TYPE5" | "TYPE6" | null,
    "evaluation_mode": "quantity_change" | "omission" | "substitution" | "additional_work" | "time_sequence_change" | null,
    "affected_boq_candidates": [],
    "affected_activity_candidates": [],
    "original_description": null,
    "replacement_description": null,
    "original_quantity": null,
    "new_quantity": null,
    "replacement_quantity": null,
    "extracted_quantities": [],
    "unit": "",
    "rate_evidence_candidates": [],
    "productivity_evidence_candidates": [],
    "supporting_documents_found": [],
    "missing_information": [],
    "confidence_score": 0.0,
    "requires_human_confirmation": true,
    "command": null
}}
Only return JSON.
"""
        elif not collected_details.get('complete'):
            # Step 2: Collect Variation Details and Extract Data
            missing_fields = []
            if not collected_details.get('affected_items'): missing_fields.append("Affected BOQ Items")
            if not collected_details.get('quantity_changes'): missing_fields.append("Quantity Changes")
            if not collected_details.get('unit'): missing_fields.append("Unit of Measurement")
            if not collected_details.get('affected_activities'): missing_fields.append("Affected Activities")
            
            prompt = f"""
You are an Expert AI Quantity Surveyor (QS).
Your role: EXTRACT DATA ONLY. NO cost/time predictions.

User Query: "{text}"
{history_str}
{context_str}

WORKFLOW STATE: Collecting Variation Details
Selected Variation Type: {variation_type}
Collected Details So Far: {collected_details}
MISSING DETAILS: {missing_fields}

Instructions:
1. Extract all quantities, units, BOQ references, activity names, and rate evidence mentioned.
2. For BOQ candidates: list descriptions that might match the variation.
3. For rate evidence: extract any quotes, rates, or cost references mentioned.
4. For productivity: extract any productivity rates or work study data mentioned.
5. Identify missing information (rate sources, productivity, drawings, etc).
6. Set confidence_score based on how complete the extracted data is (0.0 to 1.0).
7. If critical information is missing, set requires_human_confirmation = true.
8. If the user says "change X to Y", treat it as TYPE2 with evaluation_mode = substitution and extract original_description = X and replacement_description = Y.
9. If the user provides old quantity and new quantity, keep TYPE1 with evaluation_mode = quantity_change even if the narrative mentions layout or depth changes.
10. If the user says omit/remove/delete, classify as TYPE4 with evaluation_mode = omission.

MANDATORY JSON Output Format:
{{
    "reply": "Professional QS response asking for any missing details",
    "workflow_state": "collecting_details",
    "affected_boq_candidates": [
        {{"description": "item 1", "similarity_score": 0.85}},
        {{"description": "item 2", "similarity_score": 0.72}}
    ],
    "affected_activity_candidates": [
        {{"name": "activity 1", "similarity_score": 0.88}}
    ],
    "evaluation_mode": "quantity_change" | "omission" | "substitution" | "additional_work" | "time_sequence_change" | null,
    "original_description": null,
    "replacement_description": null,
    "original_quantity": null,
    "new_quantity": null,
    "replacement_quantity": null,
    "extracted_quantities": [
        {{"value": 100, "unit": "m2", "description": "original quantity"}},
        {{"value": 150, "unit": "m2", "description": "new quantity"}}
    ],
    "unit": "m2",
    "rate_evidence_candidates": [
        {{"source_type": "BOQ", "reference": "Item 5.1", "rate": 40.0}},
        {{"source_type": "quotation", "reference": "Supplier quote", "rate": 45.0}}
    ],
    "productivity_evidence_candidates": [
        {{"source_type": "schedule", "value": 50, "unit": "m2/day"}}
    ],
    "supporting_documents_found": ["quotation.pdf", "specification"],
    "missing_information": ["rate source confirmation", "drawing reference"],
    "confidence_score": 0.75,
    "requires_human_confirmation": true,
    "command": null
}}
Only return JSON.
"""
        elif not collected_details.get('additional_files_asked'):
            # Step 3: Ask for Additional Files
            prompt = f"""
You are an Expert QS. Extract data only. NO predictions.

User Query: "{text}"
Selected Variation Type: {variation_type}
Collected Details: {collected_details}

WORKFLOW STATE: Requesting Additional Files

MANDATORY JSON Output Format:
{{
    "reply": "Ask if user has BSR, HSR, quotations, specifications, or drawings to support rate/productivity evidence",
    "workflow_state": "requesting_files",
    "affected_boq_candidates": [],
    "affected_activity_candidates": [],
    "evaluation_mode": null,
    "original_description": null,
    "replacement_description": null,
    "original_quantity": null,
    "new_quantity": null,
    "replacement_quantity": null,
    "extracted_quantities": [],
    "unit": "",
    "rate_evidence_candidates": [],
    "productivity_evidence_candidates": [],
    "supporting_documents_found": [],
    "missing_information": ["awaiting supporting documents"],
    "confidence_score": 0.5,
    "requires_human_confirmation": true,
    "command": null
}}
Only return JSON.
"""
        else:
            # Step 4: Final Extraction (User-Confirmed Data Only)
            prompt = f"""
You are an Expert QS. Your ONLY task: Extract confirmed data for rule-based evaluation.

User Query: "{text}"
Variation Type: {variation_type}
Details: {collected_details}

WORKFLOW STATE: Ready for Rule-Based Evaluation

IMPORTANT: 
- Extract ONLY data user has confirmed or provided.
- Do NOT predict costs or time.
- Do NOT make calculations.
- Set requires_human_confirmation = true (final calculations require manual review).
 - Capture original and replacement descriptions when the user is changing one item into another.

MANDATORY JSON Output Format:
{{
    "reply": "Summary of extracted data. Ready for professional QS evaluation.",
    "workflow_state": "ready_for_evaluation",
    "affected_boq_candidates": [],
    "affected_activity_candidates": [],
    "evaluation_mode": "quantity_change" | "omission" | "substitution" | "additional_work" | "time_sequence_change" | null,
    "original_description": null,
    "replacement_description": null,
    "original_quantity": null,
    "new_quantity": null,
    "replacement_quantity": null,
    "extracted_quantities": [],
    "unit": "",
    "rate_evidence_candidates": [],
    "productivity_evidence_candidates": [],
    "supporting_documents_found": [],
    "missing_information": [],
    "confidence_score": 0.8,
    "requires_human_confirmation": true,
    "command": null
}}
Only return JSON.
"""

        if self.groq_client:
            try:
                response = self.groq_client.chat.completions.create(
                    model="qwen/qwen3-32b",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6,
                    max_completion_tokens=4096,
                    top_p=0.95,
                    stream=False
                )
                content = response.choices[0].message.content
                
                if "<think>" in content:
                    content = content.split("</think>")[-1].strip()

                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    import re
                    match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                    if match:
                        return json.loads(match.group(1))
                    start = content.find('{')
                    end = content.rfind('}')
                    if start != -1 and end != -1:
                        return json.loads(content[start:end+1])
                    raise
            except Exception as e:
                print(f"Groq extraction error: {e}")

        # Fallback: extraction-only JSON (no predictions)
        return {
            'reply': "Unable to connect to AI extraction service. Please try again.",
            'workflow_state': 'collecting_details',
            'affected_boq_candidates': [],
            'affected_activity_candidates': [],
            'extracted_quantities': [],
            'unit': '',
            'rate_evidence_candidates': [],
            'productivity_evidence_candidates': [],
            'supporting_documents_found': [],
            'missing_information': ['AI service unavailable'],
            'confidence_score': 0.0,
            'requires_human_confirmation': True,
            'command': None
        }
