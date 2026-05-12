"""
Session Manager for Conversation and Context Tracking
Handles session lifecycle, conversation history, and memory persistence
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
import uuid
from .storage_manager import StorageManager


class SessionManager:
    """Manages conversation sessions and context using StorageManager"""
    
    def __init__(self, storage: StorageManager):
        self.storage = storage
    
    def create_session(self, project_id: int, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new session for a project"""
        return self.storage.create_session(project_id, metadata)
    
    def get_session(self, project_id: int, session_id: int) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        project = self.storage.get_project(project_id)
        if not project: return None
        return next((s for s in project.get("sessions", []) if s["id"] == session_id), None)
    
    def get_session_by_key(self, project_id: int, session_key: str) -> Optional[Dict[str, Any]]:
        """Get session by unique key"""
        project = self.storage.get_project(project_id)
        if not project: return None
        return next((s for s in project.get("sessions", []) if s["session_key"] == session_key), None)
    
    def update_session_metadata(self, project_id: int, session_id: int, metadata: Dict) -> bool:
        """Update session metadata"""
        return self.storage.update_session_metadata(project_id, session_id, metadata)
    
    def add_message(self, project_id: int, session_id: int, role: str, content: str, 
                   metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Add a message to the session"""
        return self.storage.add_chat_message(project_id, session_id, role, content, metadata)
    
    def get_conversation_history(self, project_id: int, session_id: int, limit: int = 50) -> List[Dict]:
        """Get conversation history for a session"""
        project = self.storage.get_project(project_id)
        if not project: return []
        session = next((s for s in project.get("sessions", []) if s["id"] == session_id), None)
        if not session: return []
        
        messages = session.get("chat_history", [])
        return messages[-limit:]
    
    def get_session_context(self, project_id: int, session_id: int) -> Optional[Dict]:
        """Get complete session context"""
        project = self.storage.get_project(project_id)
        if not project: return None
        session = next((s for s in project.get("sessions", []) if s["id"] == session_id), None)
        if not session: return None
        
        # Get variations for this session
        variations = [v for v in project.get("variations", []) if v.get("session_id") == session_id]
        
        return {
            "session_id": session["id"],
            "session_key": session.get("session_key"),
            "project_id": project_id,
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "metadata": session.get("session_metadata", {}),
            "conversation_history": session.get("chat_history", []),
            'variations_count': len(variations),
            'variations': variations
        }
    
    def close_session(self, project_id: int, session_id: int) -> bool:
        """Close/complete a session"""
        project = self.storage.get_project(project_id)
        if not project: return False
        for s in project.get("sessions", []):
            if s["id"] == session_id:
                s["status"] = "completed"
                s["updated_at"] = datetime.utcnow().isoformat()
                break
        self.storage.update_project(project_id, {"sessions": project["sessions"]})
        return True
    
    def archive_session(self, project_id: int, session_id: int) -> bool:
        """Archive a session"""
        project = self.storage.get_project(project_id)
        if not project: return False
        for s in project.get("sessions", []):
            if s["id"] == session_id:
                s["status"] = "archived"
                s["updated_at"] = datetime.utcnow().isoformat()
                break
        self.storage.update_project(project_id, {"sessions": project["sessions"]})
        return True
    
    def continue_session(self, project_id: int, session_id: int) -> Dict[str, Any]:
        """Continue an existing session"""
        session = self.get_session(project_id, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found in project {project_id}")
        
        # Reactivate if needed
        if session.get("status") != "active":
            project = self.storage.get_project(project_id)
            for s in project.get("sessions", []):
                if s["id"] == session_id:
                    s["status"] = "active"
                    s["updated_at"] = datetime.utcnow().isoformat()
                    break
            self.storage.update_project(project_id, {"sessions": project["sessions"]})
        
        return self.get_session_context(project_id, session_id)
    
    def get_default_variation_state(self) -> Dict[str, Any]:
        """Default state object used to prevent the chatbot from forgetting confirmed values."""
        return {
            "variation_type": None,
            "evaluation_mode": None,

            "original_boq_item_ref": None,
            "original_description": None,
            "original_quantity": None,
            "new_quantity": None,
            "unit": None,

            "confirmed_rate": None,
            "confirmed_rate_source": None,
            "confirmed_rate_source_id": None,

            "replacement_item_ref": None,
            "replacement_description": None,
            "replacement_quantity": None,
            "replacement_rate": None,
            "replacement_rate_source": None,
            "replacement_rate_source_id": None,

            "confirmed_activity_ref": None,
            "activity_name": None,
            "confirmed_productivity": None,
            "productivity_source": None,
            "is_critical": None,
            "float_days": None,

            "supporting_documents": [],
            "human_confirmed": False,
            "missing_fields": [],

            "cost_result": None,
            "time_result": None,
            "pdf_url": None,
            "docx_url": None
        }

    def get_variation_state(self, project_id: int, session_id: int) -> Dict[str, Any]:
        """Get variation state from session metadata. Always returns a complete state object."""
        session = self.get_session(project_id, session_id)
        default_state = self.get_default_variation_state()

        if not session:
            return default_state

        metadata = session.get("session_metadata", {}) or {}
        saved_state = metadata.get("variation_state", {}) or {}

        # Merge saved state into default state so missing keys do not break workflow
        default_state.update(saved_state)
        return default_state

    def store_variation_state(self, project_id: int, session_id: int, state_updates: Dict[str, Any]) -> bool:
        """
        Store variation state safely.

        Important:
        - Existing confirmed values must not be deleted.
        - New None values must not overwrite previous real values.
        - Lists and dictionaries are preserved unless explicitly updated.
        """
        session = self.get_session(project_id, session_id)
        if not session:
            return False

        metadata = session.get("session_metadata", {}) or {}
        current_state = self.get_variation_state(project_id, session_id)

        for key, value in (state_updates or {}).items():
            # Do not overwrite existing useful data with None, empty string, or empty list
            if value is None:
                continue
            if value == "":
                continue
            if value == []:
                continue

            current_state[key] = value

        metadata["variation_state"] = current_state
        return self.update_session_metadata(project_id, session_id, metadata)

    def clear_variation_state(self, project_id: int, session_id: int) -> bool:
        """Clear variation state when starting a completely new variation."""
        session = self.get_session(project_id, session_id)
        if not session:
            return False

        metadata = session.get("session_metadata", {}) or {}
        metadata["variation_state"] = self.get_default_variation_state()
        return self.update_session_metadata(project_id, session_id, metadata)

    def get_missing_fields_for_evaluation(self, project_id: int, session_id: int) -> List[str]:
        """Return only the fields still missing for rule-based evaluation."""
        state = self.get_variation_state(project_id, session_id)
        missing = []

        evaluation_mode = state.get("evaluation_mode")
        variation_type = state.get("variation_type")

        if not variation_type:
            missing.append("variation_type")

        if not evaluation_mode:
            missing.append("evaluation_mode")

        if not state.get("original_boq_item_ref"):
            missing.append("original_boq_item_ref")

        if state.get("original_quantity") is None:
            missing.append("original_quantity")

        # Omission does not need new quantity; it becomes zero
        if evaluation_mode not in ["omission"] and variation_type != "TYPE4":
            if state.get("new_quantity") is None and state.get("replacement_quantity") is None:
                missing.append("new_or_replacement_quantity")

        if state.get("confirmed_rate") is None:
            missing.append("confirmed_rate")

        if not state.get("confirmed_rate_source"):
            missing.append("confirmed_rate_source")

        # Time fields are separate; missing time data should not block cost calculation
        if not state.get("confirmed_activity_ref"):
            missing.append("confirmed_activity_ref_for_time")

        if state.get("confirmed_productivity") is None:
            missing.append("confirmed_productivity_for_time")

        return missing
