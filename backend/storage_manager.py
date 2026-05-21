import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

class StorageManager:
    def __init__(self, data_dir: str = "backend/data"):
        if os.getenv("VERCEL") and data_dir == "backend/data":
            data_dir = "/tmp/backend_data"
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
        self.index_file = os.path.join(self.data_dir, "projects_index.json")
        self._init_index()

    def _init_index(self):
        if not os.path.exists(self.index_file):
            with open(self.index_file, 'w') as f:
                json.dump({"projects": []}, f, indent=4)

    def _get_project_file(self, project_id: int) -> str:
        return os.path.join(self.data_dir, f"project_{project_id}.json")

    def _load_json(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return {}
        with open(file_path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}

    def _save_json(self, file_path: str, data: Dict[str, Any]):
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4, default=str)

    def create_project(self, name: str, boq_filename: Optional[str] = None, 
                       rate_breakdown_filename: Optional[str] = None, 
                       schedule_filename: Optional[str] = None) -> Dict[str, Any]:
        index = self._load_json(self.index_file)
        projects = index.get("projects", [])
        if not isinstance(projects, list):
            projects = []
        index["projects"] = projects
        project_id = len(projects) + 1
        
        project_data = {
            "id": project_id,
            "name": name,
            "description": "",
            "boq_filename": boq_filename,
            "rate_breakdown_filename": rate_breakdown_filename,
            "schedule_filename": schedule_filename,
            "accepted_contract_amount": 0.0,
            "created_at": datetime.utcnow().isoformat(),
            "sheets": {},
            "boq_items": [],
            "rate_breakdowns": [],
            "rate_sources": [],
            "activities": [],
            "variations": [],
            "sessions": [],
            "chat_history": []
        }
        
        # Save project file
        self._save_json(self._get_project_file(project_id), project_data)
        
        # Update index
        projects.append({
            "id": project_id,
            "name": name,
            "created_at": project_data["created_at"]
        })
        self._save_json(self.index_file, index)
        
        return project_data

    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        file_path = self._get_project_file(project_id)
        if os.path.exists(file_path):
            return self._load_json(file_path)
        return None

    def update_project(self, project_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        project = self.get_project(project_id)
        if project:
            project.update(updates)
            self._save_json(self._get_project_file(project_id), project)
            return project
        return None

    def add_boq_items(self, project_id: int, items: List[Dict[str, Any]], sheet_name: str = "General"):
        project = self.get_project(project_id)
        if project:
            # Add sheet if not exists
            if sheet_name not in project["sheets"]:
                project["sheets"][sheet_name] = []
            
            # Add items to both global list and sheet-specific list
            start_id = len(project["boq_items"]) + 1
            for i, item in enumerate(items):
                item_with_id = {"id": start_id + i, **item, "sheet": sheet_name}
                project["boq_items"].append(item_with_id)
                project["sheets"][sheet_name].append(item_with_id["id"])
            
            self._save_json(self._get_project_file(project_id), project)
            return len(items)
        return 0

    def add_rate_breakdowns(self, project_id: int, items: List[Dict[str, Any]]):
        project = self.get_project(project_id)
        if project:
            start_id = len(project["rate_breakdowns"]) + 1
            for i, item in enumerate(items):
                item_with_id = {"id": start_id + i, **item}
                project["rate_breakdowns"].append(item_with_id)
            self._save_json(self._get_project_file(project_id), project)
            if items:
                self.add_rate_sources(project_id, [
                    {
                        **item,
                        "source_type": item.get("source_type", "rate_breakdown"),
                        "source_file": item.get("source_file") or project.get("rate_breakdown_filename"),
                    }
                    for item in items
                ])
            return len(items)
        return 0

    def _normalize_reference(self, value: Any) -> str:
        return "" if value is None else str(value).strip().lower()

    def _matches_reference(self, candidate: Any, target: Any) -> bool:
        if candidate is None or target is None:
            return False
        candidate_text = self._normalize_reference(candidate)
        target_text = self._normalize_reference(target)
        if not candidate_text or not target_text:
            return False
        return candidate_text == target_text

    def add_rate_sources(self, project_id: int, rate_sources: List[Dict[str, Any]]):
        project = self.get_project(project_id)
        if not project:
            return 0

        if "rate_sources" not in project or not isinstance(project["rate_sources"], list):
            project["rate_sources"] = []

        start_id = len(project["rate_sources"]) + 1
        for index, source in enumerate(rate_sources):
            source_id = source.get("id") or f"rate_source_{start_id + index}"
            item_with_id = {"id": source_id, **source}
            if not item_with_id.get("source_type"):
                item_with_id["source_type"] = "rate_breakdown"
            project["rate_sources"].append(item_with_id)

        self._save_json(self._get_project_file(project_id), project)
        return len(rate_sources)

    def get_rate_sources(self, project_id: int, source_type: Optional[str] = None):
        project = self.get_project(project_id)
        if not project:
            return []

        rate_sources = project.get("rate_sources", [])
        if source_type is None:
            return rate_sources

        source_type_text = self._normalize_reference(source_type)
        return [
            source for source in rate_sources
            if self._normalize_reference(source.get("source_type")) == source_type_text
        ]

    def add_activities(self, project_id: int, items: List[Dict[str, Any]]):
        project = self.get_project(project_id)
        if project:
            start_id = len(project["activities"]) + 1
            for i, item in enumerate(items):
                item_with_id = {"id": start_id + i, **item}
                project["activities"].append(item_with_id)
            self._save_json(self._get_project_file(project_id), project)
            return len(items)
        return 0

    def get_session(self, project_id: int, session_id: Any) -> Optional[Dict[str, Any]]:
        project = self.get_project(project_id)
        if not project:
            return None

        session_ref = self._normalize_reference(session_id)
        for session in project.get("sessions", []):
            possible_refs = [
                session.get("id"),
                session.get("session_id"),
                session.get("session_key"),
                session.get("ref"),
                session.get("uid"),
            ]
            if any(self._matches_reference(candidate, session_ref) for candidate in possible_refs if candidate is not None):
                return session
        return None

    def list_sessions(self, project_id: Optional[int] = None):
        if project_id is None:
            sessions = []
            for project in self.get_projects():
                current_project = self.get_project(project.get("id"))
                if current_project:
                    sessions.extend(current_project.get("sessions", []))
            return sessions

        project = self.get_project(project_id)
        if not project:
            return []
        return project.get("sessions", [])

    def create_session(self, project_id: int, session_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self.get_project(project_id)
        if project:
            if "sessions" not in project or not isinstance(project["sessions"], list):
                project["sessions"] = []
            session_id = len(project["sessions"]) + 1
            import uuid
            session = {
                "id": session_id,
                "project_id": project_id,
                "session_key": str(uuid.uuid4()),
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "session_metadata": session_metadata or {},
                "chat_history": []
            }
            project["sessions"].append(session)
            self._save_json(self._get_project_file(project_id), project)
            return session
        return {}

    def update_session_metadata(self, project_id: int, session_id: int, metadata: Dict[str, Any]) -> bool:
        project = self.get_project(project_id)
        if not project: return False
        
        for session in project.get("sessions", []):
            if session["id"] == session_id:
                if "session_metadata" not in session:
                    session["session_metadata"] = {}
                session["session_metadata"].update(metadata)
                session["updated_at"] = datetime.utcnow().isoformat()
                self._save_json(self._get_project_file(project_id), project)
                return True
        return False

    def add_chat_message(self, project_id: int, session_id: int, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        project = self.get_project(project_id)
        if project:
            if "sessions" not in project or not isinstance(project["sessions"], list):
                project["sessions"] = []
            if "chat_history" not in project or not isinstance(project["chat_history"], list):
                project["chat_history"] = []

            for session in project["sessions"]:
                if session["id"] == session_id:
                    msg_id = len(session.get("chat_history", [])) + 1
                    message = {
                        "id": msg_id,
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                        "timestamp": datetime.utcnow().isoformat(),
                        "metadata": metadata or {}
                    }
                    if "chat_history" not in session:
                        session["chat_history"] = []
                    session["chat_history"].append(message)
                    session["updated_at"] = datetime.utcnow().isoformat()
                    project["chat_history"].append(message)
                    self._save_json(self._get_project_file(project_id), project)
                    return message
        return {}

    def create_variation(self, project_id: int, session_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        project = self.get_project(project_id)
        if project:
            var_id = len(project.get("variations", [])) + 1
            variation = {
                "id": var_id,
                "project_id": project_id,
                "session_id": session_id,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "status": "Draft",
                **data
            }

            if "variations" not in project:
                project["variations"] = []

            project["variations"].append(variation)
            self._save_json(self._get_project_file(project_id), project)
            return variation

        return {}

    def add_variation(self, project_id: int, *args, **kwargs) -> Dict[str, Any]:
        """
        Backward-compatible alias for create_variation().
        Supports:
        - add_variation(project_id, variation_data)
        - add_variation(project_id, session_id, variation_data)
        - add_variation(project_id=..., session_id=..., data=...)
        """
        session_id = kwargs.get("session_id", 1)
        variation_data = kwargs.get("data") or kwargs.get("variation_data") or {}

        if len(args) == 1:
            if isinstance(args[0], dict):
                variation_data = args[0]
                session_id = variation_data.get("session_id", session_id)
            else:
                session_id = args[0]

        elif len(args) >= 2:
            session_id = args[0]
            variation_data = args[1] if isinstance(args[1], dict) else variation_data

        return self.create_variation(
            project_id=int(project_id),
            session_id=int(session_id),
            data=variation_data
        )
    
    def get_boq_item(self, project_id, item_id):
        """
        Return one BOQ item by id, item_number, item_no, item_ref, code, or ref.
        This method is required by the confirm-and-evaluate endpoint.
        """
        project = self.get_project(int(project_id))
        if not project:
            return None

        boq_items = project.get("boq_items", [])
        item_id_str = self._normalize_reference(item_id)

        for item in boq_items:
            possible_ids = [
                item.get("id"),
                item.get("item_id"),
                item.get("item_number"),
                item.get("item_no"),
                item.get("item_ref"),
                item.get("item_number_ref"),
                item.get("code"),
                item.get("ref"),
                item.get("item_ref_code"),
            ]

            if any(self._matches_reference(x, item_id_str) for x in possible_ids if x is not None):
                return item

        return None

    def get_activity(self, project_id, activity_id):
        """
        Return one schedule activity by id, activity_id, task_id, uid, ref, or code.
        This method is required by the confirm-and-evaluate endpoint.
        """
        project = self.get_project(int(project_id))
        if not project:
            return None

        activities = project.get("activities", [])
        activity_id_str = self._normalize_reference(activity_id)

        for activity in activities:
            possible_ids = [
                activity.get("id"),
                activity.get("activity_id"),
                activity.get("task_id"),
                activity.get("uid"),
                activity.get("code"),
                activity.get("ref"),
                activity.get("item_ref"),
            ]

            if any(self._matches_reference(x, activity_id_str) for x in possible_ids if x is not None):
                return activity

        return None
    
    def get_variation(self, project_id: int, variation_id: int) -> Optional[Dict[str, Any]]:
        project = self.get_project(project_id)
        if project:
            for v in project["variations"]:
                if self._matches_reference(v.get("id"), variation_id):
                    return v

        return None

    def update_variation(self, project_id: int, variation_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update an existing variation with new data"""
        project = self.get_project(project_id)
        if project:
            for i, v in enumerate(project["variations"]):
                if self._matches_reference(v.get("id"), variation_id):
                    project["variations"][i].update(updates)
                    project["variations"][i]["updated_at"] = datetime.utcnow().isoformat()
                    self._save_json(self._get_project_file(project_id), project)
                    return project["variations"][i]
        return None

    def get_projects(self) -> List[Dict[str, Any]]:
        index = self._load_json(self.index_file)
        return index.get("projects", [])

    def add_additional_file(self, project_id: int, file_data: Dict[str, Any]):
        project = self.get_project(project_id)
        if project:
            if "additional_files" not in project:
                project["additional_files"] = []
            file_id = len(project["additional_files"]) + 1
            file_record = {"id": file_id, **file_data, "project_id": project_id}
            project["additional_files"].append(file_record)
            self._save_json(self._get_project_file(project_id), project)
            return file_record
        return {}

# Singleton
storage_manager = StorageManager()
