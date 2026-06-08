import html
import logging
from typing import AnyStr, Optional, Type

from ktem.llms.manager import llms
from ktem.mcp.manager import MCP_TOOL_PREFIX, mcp_manager
from ktem.reasoning.base import BaseReasoning
from ktem.utils.generator import Generator
from ktem.utils.render import Render
from langchain.text_splitter import CharacterTextSplitter
from pydantic import BaseModel, Field

from kotaemon.agents import (
    BaseTool,
    GoogleSearchTool,
    LLMTool,
    ReactAgent,
    WikipediaTool,
)
from kotaemon.agents.tools.mcp import create_tools_from_config
from kotaemon.base import BaseComponent, Document, HumanMessage, Node, SystemMessage
from kotaemon.llms import ChatLLM, PromptTemplate

from rag.prompts import (  # component dự án (rag/prompts.py) — prompt tiếng Việt
    DOCSEARCH_TOOL_DESCRIPTION,
    REACT_QA_PROMPT,
    REACT_REWRITE_PROMPT,
)
from rag.agent_tools import (  # tool dự án (rag/agent_tools.py)
    NO_RELEVANT_DOC_MESSAGE,
    BraveSearchTool,
)

from ..utils import SUPPORTED_LANGUAGE_MAP

logger = logging.getLogger(__name__)
DEFAULT_AGENT_STEPS = 4


class DocSearchArgs(BaseModel):
    query: str = Field(..., description="a search query as input to the doc search")


class DocSearchTool(BaseTool):
    name: str = "docsearch"
    description: str = DOCSEARCH_TOOL_DESCRIPTION
    args_schema: Optional[Type[BaseModel]] = DocSearchArgs
    retrievers: list[BaseComponent] = []

    def _run_tool(self, query: AnyStr) -> AnyStr:
        docs = []
        doc_ids = []
        for retriever in self.retrievers:
            retrieved = retriever(text=query)
            # Relevance gate: chấm điểm liên quan rồi LỌC đoạn không liên quan, GIỐNG
            # simple.py (llm_trulens_score). Mục đích: agent nhận tín hiệu "không thấy"
            # rõ ràng để fallback sang web_search, thay vì luôn nhận top-k gần nhất
            # (vốn trông như có kết quả dù lạc đề). Xem rag/agent_tools.py.
            retrieved = self._filter_relevant(retriever, str(query), retrieved)
            for doc in retrieved:
                if doc.doc_id not in doc_ids:
                    docs.append(doc)
                    doc_ids.append(doc.doc_id)

        if not docs:
            return Document(content=NO_RELEVANT_DOC_MESSAGE)

        return self.prepare_evidence(docs)

    @staticmethod
    def _filter_relevant(retriever, query, docs):
        """Lọc bỏ đoạn không liên quan dựa trên điểm relevance của retriever.

        Dùng generate_relevant_scores (llm_trulens_score) khi retriever có bật LLM
        scoring — đây chính là cổng simple.py dùng. Nếu scorer KHÔNG chạy (không có
        điểm nào được gán), giữ nguyên docs để không vô tình loại sạch.
        """
        if not docs:
            return []
        scorer = getattr(retriever, "generate_relevant_scores", None)
        if scorer is not None:
            try:
                docs = scorer(query, docs)
            except Exception:
                return docs  # scorer lỗi -> không chặn, trả docs gốc
        scored = [d for d in docs if "llm_trulens_score" in d.metadata]
        if not scored:
            return docs  # scorer không chạy -> không có tín hiệu để lọc
        return [d for d in scored if d.metadata.get("llm_trulens_score", 0.0) > 0]

    # trim_len nâng 4000 -> 12000: trước đây chỉ giữ ~4000 ký tự ĐẦU (texts[0]) nên
    # với 15 đoạn truy về, các mục "Thành phần hồ sơ"/"Lệ phí" thường bị cắt mất, chỉ
    # còn "Trình tự thực hiện" -> agent thiếu dữ liệu để liệt kê giấy tờ rồi dễ bịa.
    # 12000 token < max_context_length của agent (16000) nên không bị cắt thêm.
    def prepare_evidence(self, docs, trim_len: int = 12000):
        evidence = ""
        table_found = 0

        for _id, retrieved_item in enumerate(docs):
            retrieved_content = ""
            page = retrieved_item.metadata.get("page_label", None)
            source = filename = retrieved_item.metadata.get("file_name", "-")
            if page:
                source += f" (Page {page})"
            if retrieved_item.metadata.get("type", "") == "table":
                if table_found < 5:
                    retrieved_content = retrieved_item.metadata.get("table_origin", "")
                    if retrieved_content not in evidence:
                        table_found += 1
                        evidence += (
                            f"<br><b>Table from {source}</b>\n"
                            + retrieved_content
                            + "\n<br>"
                        )
            elif retrieved_item.metadata.get("type", "") == "chatbot":
                retrieved_content = retrieved_item.metadata["window"]
                evidence += (
                    f"<br><b>Chatbot scenario from {filename} (Row {page})</b>\n"
                    + retrieved_content
                    + "\n<br>"
                )
            elif retrieved_item.metadata.get("type", "") == "image":
                retrieved_content = retrieved_item.metadata.get("image_origin", "")
                retrieved_caption = html.escape(retrieved_item.get_content())
                evidence += (
                    f"<br><b>Figure from {source}</b>\n" + retrieved_caption + "\n<br>"
                )
            else:
                if "window" in retrieved_item.metadata:
                    retrieved_content = retrieved_item.metadata["window"]
                else:
                    retrieved_content = retrieved_item.text
                retrieved_content = retrieved_content.replace("\n", " ")
                if retrieved_content not in evidence:
                    evidence += (
                        f"<br><b>Content from {source}: </b> "
                        + retrieved_content
                        + " \n<br>"
                    )

            print("Retrieved #{}: {}".format(_id, retrieved_content[:100]))
            print("Score", retrieved_item.metadata.get("reranking_score", None))

        # trim context by trim_len
        if evidence:
            text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
                chunk_size=trim_len,
                chunk_overlap=0,
                separator=" ",
                model_name="gpt-3.5-turbo",
            )
            texts = text_splitter.split_text(evidence)
            evidence = texts[0]

        return Document(content=evidence)


TOOL_REGISTRY = {
    "Google": GoogleSearchTool(),
    "Wikipedia": WikipediaTool(),
    "LLM": LLMTool(),
    "SearchDoc": DocSearchTool(),
    "WebSearch": BraveSearchTool(),  # web fallback (Brave) — xem rag/agent_tools.py
}

# Prompt tiếng Việt + domain rules — định nghĩa trong rag/prompts.py (xem import ở đầu file)
DEFAULT_QA_PROMPT = REACT_QA_PROMPT
DEFAULT_REWRITE_PROMPT = REACT_REWRITE_PROMPT


class RewriteQuestionPipeline(BaseComponent):
    """Rewrite user question

    Args:
        llm: the language model to rewrite question
        rewrite_template: the prompt template for llm to paraphrase a text input
        lang: the language of the answer. Currently support English and Japanese
    """

    llm: ChatLLM = Node(default_callback=lambda _: llms.get_default())
    rewrite_template: str = DEFAULT_REWRITE_PROMPT

    lang: str = "English"

    def run(self, question: str) -> Document:  # type: ignore
        prompt_template = PromptTemplate(self.rewrite_template)
        prompt = prompt_template.populate(question=question, lang=self.lang)
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content=prompt),
        ]
        return self.llm(messages)


class ReactAgentPipeline(BaseReasoning):
    """Question answering pipeline using ReAct agent."""

    class Config:
        allow_extra = True

    retrievers: list[BaseComponent]
    agent: ReactAgent = ReactAgent.withx()
    rewrite_pipeline: RewriteQuestionPipeline = RewriteQuestionPipeline.withx()
    use_rewrite: bool = False

    def prepare_citation(self, step_id, step, output, status) -> Document:
        header = "<b>Step {id}</b>: {log}".format(id=step_id, log=step.log)
        content = (
            "<b>Action</b>: <em>{tool}[{input}]</em>\n\n<b>Output</b>: {output}"
        ).format(
            tool=step.tool if status == "thinking" else "",
            input=step.tool_input.replace("\n", "").replace('"', "")
            if status == "thinking"
            else "",
            output=output if status == "thinking" else "Finished",
        )
        return Document(
            channel="info",
            content=Render.collapsible(
                header=header,
                content=Render.table(content),
                open=True,
            ),
        )

    async def ainvoke(  # type: ignore
        self, message, conv_id: str, history: list, **kwargs  # type: ignore
    ) -> Document:
        if self.use_rewrite:
            rewrite = await self.rewrite_pipeline(question=message)
            message = rewrite.text

        answer = self.agent(message)
        self.report_output(Document(content=answer.text, channel="chat"))

        intermediate_steps = answer.intermediate_steps
        for _, step_output in intermediate_steps:
            self.report_output(Document(content=step_output, channel="info"))

        self.report_output(None)
        return answer

    def stream(self, message, conv_id: str, history: list, **kwargs):
        if self.use_rewrite:
            rewrite = self.rewrite_pipeline(question=message)
            message = rewrite.text
            yield Document(
                channel="info",
                content=f"Rewrote the message to: {rewrite.text}",
            )

        output_stream = Generator(self.agent.stream(message))
        idx = 0
        for item in output_stream:
            idx += 1
            if item.status == "thinking":
                step, step_output = item.intermediate_steps
                yield Document(
                    channel="info",
                    content=self.prepare_citation(idx, step, step_output, item.status),
                )
            else:
                yield Document(
                    channel="chat",
                    content=item.text,
                )
                step, step_output = item.intermediate_steps
                yield Document(
                    channel="info",
                    content=self.prepare_citation(idx, step, step_output, item.status),
                )

        return output_stream.value

    @classmethod
    def get_pipeline(
        cls, settings: dict, states: dict, retrievers: list | None = None
    ) -> BaseReasoning:
        _id = cls.get_info()["id"]
        prefix = f"reasoning.options.{_id}"

        llm_name = settings[f"{prefix}.llm"]
        llm = llms.get(llm_name, llms.get_default())

        max_context_length_setting = settings.get("reasoning.max_context_length", None)

        pipeline = ReactAgentPipeline(retrievers=retrievers)
        pipeline.agent.llm = llm
        pipeline.agent.max_iterations = settings[f"{prefix}.max_iterations"]

        if max_context_length_setting:
            pipeline.agent.max_context_length = (
                max_context_length_setting // DEFAULT_AGENT_STEPS
            )

        tools = []
        for tool_name in settings[f"reasoning.options.{_id}.tools"]:
            if tool_name.startswith(MCP_TOOL_PREFIX):
                server_name = tool_name[len(MCP_TOOL_PREFIX) :]
                entry = mcp_manager.get(server_name)
                if entry:
                    config = entry["config"]
                    enabled_tools = config.pop("enabled_tools", None)
                    mcp_tools = create_tools_from_config(config, enabled_tools)
                    tools.extend(mcp_tools)
            else:
                tool = TOOL_REGISTRY[tool_name]
                if tool_name == "SearchDoc":
                    tool.retrievers = retrievers
                elif tool_name == "LLM":
                    tool.llm = llm
                tools.append(tool)
        pipeline.agent.plugins = tools
        pipeline.agent.output_lang = SUPPORTED_LANGUAGE_MAP.get(
            settings["reasoning.lang"], "English"
        )
        pipeline.rewrite_pipeline.lang = pipeline.agent.output_lang
        pipeline.use_rewrite = states.get("app", {}).get("regen", False)
        pipeline.agent.prompt_template = PromptTemplate(settings[f"{prefix}.qa_prompt"])

        return pipeline

    @classmethod
    def get_user_settings(cls) -> dict:
        llm = ""
        llm_choices = [("(default)", "")]
        try:
            llm_choices += [(_, _) for _ in llms.options().keys()]
        except Exception as e:
            logger.exception(f"Failed to get LLM options: {e}")

        tool_choices = ["SearchDoc", "WebSearch", "Wikipedia", "Google", "LLM"]
        try:
            tool_choices += mcp_manager.list_registered_mcp_servers()
        except Exception as e:
            logger.exception(f"Failed to get MCP tool options: {e}")

        return {
            "llm": {
                "name": "Language model",
                "value": llm,
                "component": "dropdown",
                "choices": llm_choices,
                "special_type": "llm",
                "info": (
                    "The language model to use for generating the answer. If None, "
                    "the application default language model will be used."
                ),
            },
            "tools": {
                "name": "Tools for knowledge retrieval",
                # Mặc định: docsearch (corpus nội bộ) + web_search (fallback Brave).
                # Bỏ "LLM" (dummy_mode + dễ bịa, trái nguyên tắc chỉ dùng tài liệu).
                "value": ["SearchDoc", "WebSearch"],
                "component": "checkboxgroup",
                "choices": tool_choices,
            },
            "max_iterations": {
                "name": "Maximum number of iterations the LLM can go through",
                "value": 5,
                "component": "number",
            },
            "qa_prompt": {
                "name": "QA Prompt",
                "value": DEFAULT_QA_PROMPT,
            },
        }

    @classmethod
    def get_info(cls) -> dict:
        return {
            "id": "ReAct",
            "name": "ReAct Agent",
            "description": (
                "Implementing ReAct paradigm: https://arxiv.org/abs/2210.03629. "
                "ReAct agent answers the user's request by iteratively formulating "
                "plan and executing it. The agent can use multiple tools to gather "
                "information and generate the final answer."
            ),
        }
