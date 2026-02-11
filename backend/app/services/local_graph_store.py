import json
import os
import threading
from typing import Dict, Any, List, Optional
from pathlib import Path
from ..config import Config

class LocalGraphStore:
    """
    Local file-based graph store.
    Stores graph data in JSON format at backend/data/graphs/<graph_id>.json
    """
    
    _lock = threading.Lock()
    
    @staticmethod
    def _get_file_path(graph_id: str) -> Path:
        base_dir = Path(os.getcwd()) / "backend" / "data" / "graphs"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / f"{graph_id}.json"

    @classmethod
    def load_graph(cls, graph_id: str) -> Dict[str, Any]:
        """
        Load graph data from JSON file.
        Returns empty structure if file doesn't exist.
        """
        file_path = cls._get_file_path(graph_id)
        if not file_path.exists():
            return {
                "graph_id": graph_id,
                "nodes": {},  # Changed to dict for easier lookup by name/uuid
                "edges": []
            }
            
        with cls._lock:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading graph {graph_id}: {e}")
                return {
                    "graph_id": graph_id,
                    "nodes": {},
                    "edges": []
                }

    @classmethod
    def save_graph(cls, graph_data: Dict[str, Any]):
        """Save graph data to JSON file."""
        graph_id = graph_data.get("graph_id")
        if not graph_id:
            raise ValueError("Graph data must contain graph_id")
            
        file_path = cls._get_file_path(graph_id)
        
        with cls._lock:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(graph_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Error saving graph {graph_id}: {e}")
                raise

    @classmethod
    def upsert_entities(cls, graph_id: str, entities: List[Dict[str, Any]]):
        """
        Update or insert entities.
        entities: List of dicts with 'name', 'type', 'summary', etc.
        """
        data = cls.load_graph(graph_id)
        
        if "nodes" not in data:
            data["nodes"] = {}
            
        for entity in entities:
            name = entity.get("name")
            if not name:
                continue
                
            # Key by name for deduplication
            existing_node = data["nodes"].get(name)
            
            if existing_node:
                # Update existing
                # Merge logic can be refined here. For now, overwrite/append info
                if entity.get("summary"):
                    existing_node["summary"] = entity["summary"]
                if entity.get("type"):
                    if "labels" not in existing_node:
                        existing_node["labels"] = []
                    if entity["type"] not in existing_node["labels"]:
                        existing_node["labels"].append(entity["type"])
                # Merge attributes
                if "attributes" in entity:
                    if "attributes" not in existing_node:
                        existing_node["attributes"] = {}
                    existing_node["attributes"].update(entity["attributes"])
            else:
                # Create new
                import uuid
                new_node = {
                    "uuid": str(uuid.uuid4()),
                    "name": name,
                    "labels": [entity.get("type")] if entity.get("type") else [],
                    "summary": entity.get("summary", ""),
                    "attributes": entity.get("attributes", {})
                }
                data["nodes"][name] = new_node
                
        cls.save_graph(data)

    @classmethod
    def upsert_relations(cls, graph_id: str, relations: List[Dict[str, Any]]):
        """
        Update or insert relations.
        relations: List of dicts with 'source', 'target', 'relation', 'fact'
        """
        data = cls.load_graph(graph_id)
        
        # We need to ensure source/target nodes exist, or at least have UUIDs
        # If they don't exist in 'nodes', we should probably create placeholders or skip?
        # User requirement says: "extract entities... extract relations"
        # Usually entities come first or together.
        # We will assume nodes are upserted first or we look them up.
        
        if "nodes" not in data:
            data["nodes"] = {}
        if "edges" not in data:
            data["edges"] = []
            
        for rel in relations:
            source_name = rel.get("source")
            target_name = rel.get("target")
            relation_type = rel.get("relation")
            
            if not source_name or not target_name or not relation_type:
                continue
                
            # Find node UUIDs
            source_node = data["nodes"].get(source_name)
            target_node = data["nodes"].get(target_name)
            
            if not source_node or not target_node:
                # If nodes don't exist, we might skip this edge or create placeholder nodes.
                # Let's skip for safety to avoid dangling edges, 
                # OR create them if we want to be robust. 
                # Given strict extraction, let's create placeholders if missing.
                import uuid
                if not source_node:
                    source_node = {
                        "uuid": str(uuid.uuid4()), 
                        "name": source_name, 
                        "labels": ["Unknown"], 
                        "summary": "", 
                        "attributes": {}
                    }
                    data["nodes"][source_name] = source_node
                if not target_node:
                    target_node = {
                        "uuid": str(uuid.uuid4()), 
                        "name": target_name, 
                        "labels": ["Unknown"], 
                        "summary": "", 
                        "attributes": {}
                    }
                    data["nodes"][target_name] = target_node
            
            # Create Edge
            import uuid
            new_edge = {
                "uuid": str(uuid.uuid4()),
                "name": relation_type,
                "fact": rel.get("fact", ""),
                "source_node_uuid": source_node["uuid"],
                "target_node_uuid": target_node["uuid"],
                "attributes": rel.get("attributes", {})
            }
            data["edges"].append(new_edge)
            
        cls.save_graph(data)

    @classmethod
    def get_d3_data(cls, graph_id: str) -> Dict[str, Any]:
        """
        Convert stored data to D3 format expected by frontend.
        """
        data = cls.load_graph(graph_id)
        
        nodes_list = []
        if "nodes" in data:
            for name, node in data["nodes"].items():
                nodes_list.append(node)
                
        return {
            "graph_id": graph_id,
            "nodes": nodes_list,
            "edges": data.get("edges", []),
            "node_count": len(nodes_list),
            "edge_count": len(data.get("edges", []))
        }
