"""
图谱构建服务
使用 Mem0 进行记忆存储，使用本地 LLM + JSON 构建图谱
"""

import os
import uuid
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

# from mem0 import Memory # 移除 SDK 依赖
from .mem0_client import Mem0Client

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from .text_processor import TextProcessor
from .local_graph_store import LocalGraphStore
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph_builder')

@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    图谱构建服务
    负责调用 Mem0 存储记忆，并调用 LLM 抽取三元组存入本地 JSON
    """
    
    def __init__(self, api_key: Optional[str] = None):
        # B5. Mem0 初始化检查
        # 1. 检查必要配置
        # if not Config.LLM_API_KEY:
        #     raise ValueError("LLM_API_KEY 未配置，Mem0 需要 API Key 才能工作")
            
        # 2. 设置 Mem0 所需的环境变量 (默认使用 OpenAI)
        # if not os.environ.get("OPENAI_API_KEY"):
        #     os.environ["OPENAI_API_KEY"] = Config.LLM_API_KEY
            
        # 3. 初始化 Mem0 Client (REST)
        try:
            # 使用自定义 REST Client，只依赖 MEM0_API_KEY
            self.mem0_client = Mem0Client()
        except Exception as e:
            logger.error(f"Mem0 Client 初始化失败: {e}")
            # Client 初始化失败通常是因为缺少配置，但也可能是其他原因
            # 由于我们要求不阻断构建，这里可以只记录日志，或者抛出异常让上层处理
            # 鉴于 __init__ 失败通常意味着服务不可用，这里 Fail Fast 是合理的
            # 但如果 MEM0_API_KEY 缺失，Mem0Client 会在内部 warning，不会抛异常
            # 所以这里抛异常通常是其他严重错误
            raise RuntimeError(f"Mem0 Client 初始化失败: {e}") from e
            
        self.task_manager = TaskManager()
        self.llm_client = LLMClient()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3 # 保留参数兼容性，但实际处理可能逐个进行
    ) -> str:
        """
        异步构建图谱
        """
        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def create_graph(self, name: str) -> str:
        """创建图谱ID (本地生成 UUID)"""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        # 这里不需要在 Mem0 或 LocalStore 做预先创建，只需返回 ID
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """
        设置本体
        对于本地 JSON 方案，本体主要用于抽取时的 Prompt，
        这里可以选择将本体保存到 graph json 中，或者什么都不做。
        为了元数据完整性，我们将其保存到 LocalGraphStore (如果支持) 
        或者仅在构建时使用。
        目前 LocalGraphStore 结构主要存 nodes/edges。
        我们可以暂存到内存或不持久化本体到 JSON (因为抽取时会传入)。
        为了简单，这里不做操作，抽取时会直接使用传入的 ontology。
        """
        pass

    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int
    ):
        """图谱构建工作线程"""
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="开始构建图谱..."
            )
            
            # 1. 生成 Graph ID
            graph_id = self.create_graph(graph_name)
            logger.info(f"Generated graph_id: {graph_id}")
            logger.info(f"LocalGraphStore path: {LocalGraphStore._get_file_path(graph_id)}")
            
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=f"图谱ID已生成: {graph_id}"
            )
            
            # 2. 文本分块
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=f"文本已分割为 {total_chunks} 个块"
            )
            
            # 3. 逐块处理 (并行管线 A & B)
            processed_count = 0
            
            for chunk in chunks:
                processed_count += 1
                progress_base = 15
                progress_step = 80 / total_chunks # 剩余 80% 进度分配给处理
                current_progress = int(progress_base + (processed_count / total_chunks) * 80)
                
                self.task_manager.update_task(
                    task_id,
                    progress=current_progress,
                    message=f"正在处理第 {processed_count}/{total_chunks} 块..."
                )
                
                # --- 管线 A: 记忆与检索 (Mem0) ---
                try:
                    # 使用 REST Client
                    self.mem0_client.add(
                        messages=[{'role': 'user', 'content': chunk}], 
                        user_id=graph_id
                    )
                except Exception as e:
                    logger.warning(f"Mem0 add failed for chunk {processed_count}: {e}")
                    # Mem0 失败不应阻断流程，特别是 Free 版可能有限制，但应记录
                
                # --- 管线 B: 图谱构建 (本地) ---
                try:
                    triples = self.extract_triples_with_llm(chunk, ontology)
                    
                    # 打印日志 (验收标准)
                    entities_count = len(triples.get("entities", []))
                    relations_count = len(triples.get("relations", []))
                    logger.info(f"Chunk {processed_count}: Extracted {entities_count} entities, {relations_count} relations. GraphID: {graph_id}")
                    
                    if entities_count > 0:
                        LocalGraphStore.upsert_entities(graph_id, triples["entities"])
                    if relations_count > 0:
                        LocalGraphStore.upsert_relations(graph_id, triples["relations"])
                        
                except Exception as e:
                    logger.error(f"Local extraction failed for chunk {processed_count}: {e}")
                    # 抽取失败也不阻断
            
            # 4. 获取最终信息
            self.task_manager.update_task(
                task_id,
                progress=95,
                message="正在生成图谱统计信息..."
            )
            
            graph_info = self._get_graph_info(graph_id)
            
            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            self.task_manager.fail_task(task_id, error_msg)

    def extract_triples_with_llm(self, text: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用 LLM 抽取实体和关系
        """
        entity_types = [e["name"] for e in ontology.get("entity_types", [])]
        edge_types = [e["name"] for e in ontology.get("edge_types", [])]
        
        prompt = f"""
你是一个专业的知识图谱构建助手。请分析下面的文本，提取实体和关系。

## 本体定义
实体类型: {json.dumps(entity_types, ensure_ascii=False)}
关系类型: {json.dumps(edge_types, ensure_ascii=False)}

## 提取要求
1. 仅提取上述定义的实体类型和关系类型。
2. 输出格式必须是严格的 JSON。
3. 不要臆造信息，不确定的不要输出。

## 输出格式示例
{{
  "entities": [
    {{"name": "实体名称", "type": "实体类型", "summary": "简要描述"}}
  ],
  "relations": [
    {{"source": "源实体名", "target": "目标实体名", "relation": "关系类型", "fact": "关系描述"}}
  ]
}}

## 待分析文本
{text}
"""
        messages = [{"role": "user", "content": prompt}]
        
        try:
            return self.llm_client.chat_json(messages=messages, temperature=0.1)
        except Exception as e:
            logger.error(f"LLM extraction error: {e}")
            return {"entities": [], "relations": []}

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        data = LocalGraphStore.get_d3_data(graph_id)
        
        entity_types = set()
        for node in data.get("nodes", []):
            if "labels" in node:
                for label in node["labels"]:
                    entity_types.add(label)
                    
        return GraphInfo(
            graph_id=graph_id,
            node_count=data.get("node_count", 0),
            edge_count=data.get("edge_count", 0),
            entity_types=list(entity_types)
        )
    
    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """获取完整图谱数据 (D3 兼容)"""
        return LocalGraphStore.get_d3_data(graph_id)
    
    def delete_graph(self, graph_id: str):
        """删除图谱"""
        # 1. 删除本地文件
        file_path = LocalGraphStore._get_file_path(graph_id)
        if file_path.exists():
            os.remove(file_path)
            
        # 2. 删除 Mem0 记忆 (如果有 delete API)
        try:
            self.mem0_client.delete_all(user_id=graph_id)
        except Exception as e:
            logger.warning(f"Failed to delete mem0 memory for {graph_id}: {e}")

    def add_text_batches(self, *args, **kwargs):
        """兼容旧接口，实际上不再使用"""
        pass
        
    def _wait_for_episodes(self, *args, **kwargs):
        """兼容旧接口，不再需要等待"""
        pass
