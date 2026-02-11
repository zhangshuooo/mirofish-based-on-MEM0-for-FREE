"""
Mem0 REST Client
替代 Mem0 SDK，直接调用 Mem0 云服务 API，避免对 OpenAI API Key 的硬依赖。
"""

import os
import requests
import json
from typing import Dict, Any, List, Optional
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.mem0_client')

class Mem0Client:
    """
    Mem0 REST API 客户端
    仅支持 add 和 search 操作
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.MEM0_API_KEY
        if not self.api_key:
            logger.warning("MEM0_API_KEY 未配置，Mem0 功能将不可用")
            
        self.base_url = "https://api.mem0.ai/v1"
        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def add(self, messages: List[Dict[str, str]], user_id: str, output_format: str = "v1.0") -> Dict[str, Any]:
        """
        添加记忆
        POST /v1/memories/
        """
        if not self.api_key:
            logger.warning("跳过 Mem0 add: API Key 未配置")
            return {}
            
        url = f"{self.base_url}/memories/"
        payload = {
            "messages": messages,
            "user_id": user_id,
            "enable_graph": False,  # 强制禁用图谱功能
            "output_format": output_format
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"Mem0 add failed: {str(e)}"
            if hasattr(e, 'response') and e.response:
                try:
                    error_detail = e.response.json()
                    error_msg += f" - {json.dumps(error_detail)}"
                except:
                    error_msg += f" - {e.response.text}"
            logger.warning(error_msg)
            raise RuntimeError(error_msg) from e

    def search(self, query: str, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索记忆
        POST /v1/memories/search/
        """
        if not self.api_key:
            logger.warning("跳过 Mem0 search: API Key 未配置")
            return []
            
        url = f"{self.base_url}/memories/search/"
        payload = {
            "query": query,
            "user_id": user_id,
            "limit": limit
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"Mem0 search failed: {str(e)}"
            if hasattr(e, 'response') and e.response:
                try:
                    error_detail = e.response.json()
                    error_msg += f" - {json.dumps(error_detail)}"
                except:
                    error_msg += f" - {e.response.text}"
            logger.error(error_msg)
            # 搜索失败通常返回空列表，避免阻断上层逻辑
            return []

    def delete_all(self, user_id: str):
        """
        删除用户的所有记忆
        DELETE /v1/memories/
        """
        if not self.api_key:
            return
            
        url = f"{self.base_url}/memories/"
        params = {"user_id": user_id}
        
        try:
            response = requests.delete(url, headers=self.headers, params=params, timeout=30)
            if response.status_code != 404: # 404 means already deleted or not found, which is fine
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Mem0 delete failed: {str(e)}")
