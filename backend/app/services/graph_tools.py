"""
图谱检索工具服务
封装图谱搜索、节点读取、边查询等工具，供Report Agent使用
替代原有的 ZepToolsService
"""

import time
import json
import logging
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from .mem0_client import Mem0Client

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from .local_graph_store import LocalGraphStore

logger = get_logger('mirofish.graph_tools')

@dataclass
class SearchResult:
    """搜索结果"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """转换为文本格式，供LLM理解"""
        text_parts = [f"搜索查询: {self.query}", f"找到 {self.total_count} 条相关信息"]
        
        if self.facts:
            text_parts.append("\n### 相关事实:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)

@dataclass
class NodeInfo:
    """节点信息"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }

@dataclass
class EdgeInfo:
    """边信息"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }
    
    @property
    def is_expired(self) -> bool:
        return self.expired_at is not None
        
    @property
    def is_invalid(self) -> bool:
        return self.invalid_at is not None

@dataclass
class InsightForgeResult:
    """深度洞察检索结果"""
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    semantic_facts: List[str] = field(default_factory=list)
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)
    relationship_chains: List[str] = field(default_factory=list)
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        text_parts = [
            f"## 未来预测深度分析",
            f"分析问题: {self.query}",
            f"预测场景: {self.simulation_requirement}",
            f"\n### 预测数据统计",
            f"- 相关预测事实: {self.total_facts}条",
            f"- 涉及实体: {self.total_entities}个",
            f"- 关系链: {self.total_relationships}条"
        ]
        
        if self.sub_queries:
            text_parts.append(f"\n### 分析的子问题")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")

        if self.semantic_facts:
            text_parts.append(f"\n### 【关键事实】")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
                
        if self.entity_insights:
            text_parts.append(f"\n### 【核心实体】")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', '未知')}** ({entity.get('type', '实体')})")
                if entity.get('summary'):
                    text_parts.append(f"  摘要: \"{entity.get('summary')}\"")
        
        if self.relationship_chains:
            text_parts.append(f"\n### 【关系链】")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
                
        return "\n".join(text_parts)

@dataclass
class PanoramaResult:
    """广度搜索结果"""
    query: str
    all_nodes: List[NodeInfo] = field(default_factory=list)
    all_edges: List[EdgeInfo] = field(default_factory=list)
    active_facts: List[str] = field(default_factory=list)
    historical_facts: List[str] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
        
    def to_text(self) -> str:
        text_parts = [
            f"## 广度搜索结果（未来全景视图）",
            f"查询: {self.query}",
            f"\n### 统计信息",
            f"- 总节点数: {self.total_nodes}",
            f"- 总边数: {self.total_edges}",
            f"- 当前有效事实: {self.active_count}条",
            f"- 历史/过期事实: {self.historical_count}条"
        ]
        
        if self.active_facts:
            text_parts.append(f"\n### 【当前有效事实】")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        if self.historical_facts:
            text_parts.append(f"\n### 【历史/过期事实】")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
                
        return "\n".join(text_parts)

@dataclass
class AgentInterview:
    """单个Agent的采访结果"""
    agent_name: str
    agent_role: str
    agent_bio: str
    question: str
    response: str
    key_quotes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        text += f"_简介: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**关键引言:**\n"
            for quote in self.key_quotes:
                text += f"> \"{quote}\"\n"
        return text

@dataclass
class InterviewResult:
    """采访结果"""
    interview_topic: str
    interview_questions: List[str]
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    interviews: List[AgentInterview] = field(default_factory=list)
    selection_reasoning: str = ""
    summary: str = ""
    total_agents: int = 0
    interviewed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        text_parts = [
            f"## 深度采访报告",
            f"**采访主题:** {self.interview_topic}",
            f"**采访人数:** {self.interviewed_count}",
            f"\n### 采访摘要",
            self.summary
        ]
        if self.interviews:
            text_parts.append(f"\n### 采访实录")
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### 采访 #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        return "\n".join(text_parts)


class GraphToolsService:
    """
    图谱检索工具服务 (Local + Mem0)
    替代原有的 ZepToolsService
    """
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        # api_key 参数保留但忽略 (Mem0 使用 env)
        self.mem0_client = Mem0Client()
        self._llm_client = llm_client
        logger.info("GraphToolsService 初始化完成 (Mem0 + LocalGraphStore)")
    
    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges" # 保留参数兼容
    ) -> SearchResult:
        """
        基于 Mem0 的语义搜索
        """
        logger.info(f"Mem0 搜索: graph_id={graph_id}, query={query[:50]}...")
        
        try:
            # Mem0 search
            results = self.mem0_client.search(query, user_id=graph_id, limit=limit)
            
            facts = []
            for res in results:
                # Mem0 结果格式: {'id': ..., 'memory': 'text...', 'score': ...}
                if 'memory' in res:
                    facts.append(res['memory'])
            
            logger.info(f"搜索完成: 找到 {len(facts)} 条相关记忆")
            
            return SearchResult(
                facts=facts,
                edges=[], # Mem0 不返回边
                nodes=[], # Mem0 不返回节点
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            logger.error(f"Mem0 搜索失败: {e}")
            return SearchResult(facts=[], edges=[], nodes=[], query=query, total_count=0)

    def quick_search(self, graph_id: str, query: str, limit: int = 10) -> SearchResult:
        """简单搜索"""
        return self.search_graph(graph_id, query, limit)

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """深度洞察检索"""
        logger.info(f"InsightForge 深度洞察: {query[:50]}...")
        
        # 1. 生成子问题
        sub_queries = self._generate_sub_queries(query, simulation_requirement, report_context, max_sub_queries)
            
        # 2. 搜索
        all_facts = set()
        all_edges = []
        
        # 主查询搜索
        main_res = self.search_graph(graph_id, query, limit=10)
        for f in main_res.facts:
            all_facts.add(f)
            
        # 子查询搜索
        for sq in sub_queries:
            res = self.search_graph(graph_id, sq, limit=5)
            for f in res.facts:
                all_facts.add(f)
        
        # 3. 实体洞察和关系链 (从本地图谱中查找关联)
        # 由于Mem0不返回结构化边，我们需要从本地图谱中查找与事实相关的实体
        # 这里做一个简化处理：从本地图谱获取所有节点，如果节点名称出现在事实中，则认为相关
        
        all_nodes = self.get_all_nodes(graph_id)
        all_local_edges = self.get_all_edges(graph_id)
        
        entity_insights = []
        relationship_chains = []
        
        # 简单的实体匹配
        relevant_node_uuids = set()
        facts_list = list(all_facts)
        full_text = " ".join(facts_list).lower()
        
        for node in all_nodes:
            if node.name.lower() in full_text:
                relevant_node_uuids.add(node.uuid)
                entity_insights.append({
                    "uuid": node.uuid,
                    "name": node.name,
                    "type": next((l for l in node.labels if l not in ["Entity", "Node"]), "实体"),
                    "summary": node.summary,
                    "related_facts": [f for f in facts_list if node.name.lower() in f.lower()]
                })
        
        # 查找相关边
        for edge in all_local_edges:
            if edge.source_node_uuid in relevant_node_uuids and edge.target_node_uuid in relevant_node_uuids:
                chain = f"{edge.source_node_name} --[{edge.name}]--> {edge.target_node_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
                
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=sub_queries,
            semantic_facts=list(all_facts),
            entity_insights=entity_insights,
            relationship_chains=relationship_chains,
            total_facts=len(all_facts),
            total_entities=len(entity_insights),
            total_relationships=len(relationship_chains)
        )
        return result

    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """使用LLM生成子问题"""
        system_prompt = """你是一个专业的问题分析专家。你的任务是将一个复杂问题分解为多个可以在模拟世界中独立观察的子问题。
要求：
1. 每个子问题应该足够具体
2. 子问题应该覆盖原问题的不同维度
3. 返回JSON格式：{"sub_queries": ["子问题1", "子问题2", ...]}"""

        user_prompt = f"""模拟需求背景：{simulation_requirement}
{f"报告上下文：{report_context[:500]}" if report_context else ""}
请将以下问题分解为{max_queries}个子问题：
{query}
返回JSON格式的子问题列表。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            sub_queries = response.get("sub_queries", [])
            return [str(sq) for sq in sub_queries[:max_queries]]
        except Exception as e:
            logger.warning(f"生成子问题失败: {str(e)}")
            return [query]

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """从本地存储获取所有节点"""
        data = LocalGraphStore.get_d3_data(graph_id)
        nodes = []
        for n in data.get("nodes", []):
            nodes.append(NodeInfo(
                uuid=n.get("uuid", ""),
                name=n.get("name", ""),
                labels=n.get("labels", []),
                summary=n.get("summary", ""),
                attributes=n.get("attributes", {})
            ))
        return nodes

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """从本地存储获取所有边"""
        data = LocalGraphStore.get_d3_data(graph_id)
        edges = []
        # 建立节点映射以获取名称
        node_map = {n["uuid"]: n["name"] for n in data.get("nodes", [])}
        
        for e in data.get("edges", []):
            s_uuid = e.get("source_node_uuid")
            t_uuid = e.get("target_node_uuid")
            edges.append(EdgeInfo(
                uuid=e.get("uuid", ""),
                name=e.get("name", ""),
                fact=e.get("fact", ""),
                source_node_uuid=s_uuid,
                target_node_uuid=t_uuid,
                source_node_name=node_map.get(s_uuid),
                target_node_name=node_map.get(t_uuid),
                created_at=e.get("created_at"),
                valid_at=e.get("valid_at"),
                invalid_at=e.get("invalid_at"),
                expired_at=e.get("expired_at")
            ))
        return edges

    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """广度搜索 - 基于本地图谱数据"""
        # 获取所有数据
        all_nodes = self.get_all_nodes(graph_id)
        all_edges = self.get_all_edges(graph_id)
        
        # 简单的关键词过滤
        query_lower = query.lower()
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            fact_text = edge.fact or edge.name
            if query_lower in fact_text.lower():
                is_expired_edge = edge.is_expired or edge.is_invalid
                if is_expired_edge:
                    if include_expired:
                        historical_facts.append(fact_text)
                else:
                    active_facts.append(fact_text)
                
        return PanoramaResult(
            query=query,
            all_nodes=all_nodes,
            all_edges=all_edges,
            active_facts=active_facts[:limit],
            historical_facts=historical_facts[:limit],
            total_nodes=len(all_nodes),
            total_edges=len(all_edges),
            active_count=len(active_facts),
            historical_count=len(historical_facts)
        )

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None
    ) -> InterviewResult:
        """
        深度采访 - 移植自 ZepToolsService
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(f"InterviewAgents 深度采访（真实API）: {interview_requirement[:50]}...")
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Step 1: 读取人设文件
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(f"未找到模拟 {simulation_id} 的人设文件")
            result.summary = "未找到可采访的Agent人设文件"
            return result
        
        result.total_agents = len(profiles)
        logger.info(f"加载到 {len(profiles)} 个Agent人设")
        
        # Step 2: 使用LLM选择要采访的Agent
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        
        # Step 3: 生成采访问题
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
        
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        INTERVIEW_PROMPT_PREFIX = "结合你的人设、所有的过往记忆与行动，不调用任何工具直接用文本回复我："
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Step 4: 调用真实的采访API
        try:
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt
                })
            
            logger.info(f"调用批量采访API（双平台）: {len(interviews_request)} 个Agent")
            
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,
                timeout=180.0
            )
            
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "未知错误")
                result.summary = f"采访API调用失败：{error_msg}。请检查OASIS模拟环境状态。"
                return result
            
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "未知")
                agent_bio = agent.get("bio", "")
                
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")
                
                response_parts = []
                if twitter_response:
                    response_parts.append(f"【Twitter平台回答】\n{twitter_response}")
                if reddit_response:
                    response_parts.append(f"【Reddit平台回答】\n{reddit_response}")
                
                response_text = "\n\n".join(response_parts) if response_parts else "[无回复]"
                
                # 提取关键引言
                import re
                combined_responses = f"{twitter_response} {reddit_response}"
                key_quotes = re.findall(r'[""「」『』]([^""「」『』]{10,100})[""「」『』]', combined_responses)
                if not key_quotes:
                    sentences = combined_responses.split('。')
                    key_quotes = [s.strip() + '。' for s in sentences if len(s.strip()) > 20][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except Exception as e:
            logger.error(f"采访API调用异常: {e}")
            result.summary = f"采访过程发生错误：{str(e)}"
            return result
        
        # Step 6: 生成采访摘要
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        return result

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """加载模拟的Agent人设文件"""
        import os
        import csv
        
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # 优先尝试读取Reddit JSON格式
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                return profiles
            except Exception:
                pass
        
        # 尝试读取Twitter CSV格式
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "未知"
                        })
                return profiles
            except Exception:
                pass
        
        return profiles

    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """使用LLM选择要采访的Agent"""
        
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "未知"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """你是一个专业的采访策划专家。你的任务是根据采访需求，从模拟Agent列表中选择最适合采访的对象。
返回JSON格式：
{
    "selected_indices": [选中Agent的索引列表],
    "reasoning": "选择理由说明"
}"""

        user_prompt = f"""采访需求：{interview_requirement}
模拟背景：{simulation_requirement if simulation_requirement else "未提供"}
可选择的Agent列表（共{len(agent_summaries)}个）：
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}
请选择最多{max_agents}个最适合采访的Agent，并说明选择理由。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "基于相关性自动选择")
            
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(f"LLM选择Agent失败: {e}")
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "使用默认选择策略"

    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """使用LLM生成采访问题"""
        
        agent_roles = [a.get("profession", "未知") for a in selected_agents]
        
        system_prompt = """你是一个专业的记者。根据采访需求，生成3-5个深度采访问题。
返回JSON格式：{"questions": ["问题1", "问题2", ...]}"""

        user_prompt = f"""采访需求：{interview_requirement}
模拟背景：{simulation_requirement if simulation_requirement else "未提供"}
采访对象角色：{', '.join(agent_roles)}
请生成3-5个采访问题。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            return response.get("questions", [f"关于{interview_requirement}，您有什么看法？"])
        except Exception:
            return [f"关于{interview_requirement}，您的观点是什么？"]

    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """生成采访摘要"""
        if not interviews:
            return "未完成任何采访"
        
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"【{interview.agent_name}（{interview.agent_role}）】\n{interview.response[:500]}")
        
        system_prompt = """你是一个专业的新闻编辑。请根据多位受访者的回答，生成一份采访摘要。"""
        user_prompt = f"""采访主题：{interview_requirement}
采访内容：
{"".join(interview_texts)}
请生成采访摘要。"""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
        except Exception:
            return f"共采访了{len(interviews)}位受访者。"
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        data = LocalGraphStore.get_d3_data(graph_id)
        return {
            "graph_id": graph_id,
            "total_nodes": data.get("node_count", 0),
            "total_edges": data.get("edge_count", 0)
        }
