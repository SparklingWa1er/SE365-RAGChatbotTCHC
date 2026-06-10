import html
import logging
import re
from textwrap import dedent
from typing import AnyStr, Optional, Type

from ktem.embeddings.manager import embedding_models_manager as embeddings
from ktem.llms.manager import llms
from ktem.mcp.manager import MCP_TOOL_PREFIX, mcp_manager
from ktem.reasoning.base import BaseReasoning
from ktem.utils.generator import Generator
from ktem.utils.render import Render
from ktem.utils.visualize_cited import CreateCitationVizPipeline
from langchain.text_splitter import CharacterTextSplitter
from plotly.io import to_json
from pydantic import BaseModel, Field

from kotaemon.agents import (
    BaseTool,
    GoogleSearchTool,
    LLMTool,
    ReactAgent,
    WikipediaTool,
)
from kotaemon.agents.tools.mcp import create_tools_from_config
from kotaemon.base import (
    BaseComponent,
    Document,
    HumanMessage,
    Node,
    SystemMessage,
)
from kotaemon.indices.qa.citation_qa import CONTEXT_RELEVANT_WARNING_SCORE
from kotaemon.indices.qa.citation_qa_inline import AnswerWithInlineCitation
from kotaemon.indices.qa.format_context import PrepareEvidencePipeline
from kotaemon.indices.qa.utils import replace_think_tag_with_details
from kotaemon.llms import ChatLLM, PromptTemplate

from rag.prompts import (  # component dự án (rag/prompts.py) — prompt tiếng Việt
    DOCSEARCH_TOOL_DESCRIPTION,
    REACT_QA_CITATION_PROMPT,
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
    # Bể gom nguồn (do pipeline gán mỗi request): các đoạn liên quan truy được sẽ được
    # append vào đây để pha synthesis tạo inline citation. None = không gom (vẫn chạy bình
    # thường cho vòng lặp agent). Xem reasoning/react.py:ReactAgentPipeline.get_pipeline.
    doc_sink: Optional[list] = None

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

        # Gom các đoạn liên quan (đã có llm_trulens_score) cho pha synthesis. Dedup theo
        # doc_id để nhiều lượt docsearch không nhân đôi nguồn.
        if self.doc_sink is not None:
            existing = {getattr(d, "doc_id", None) for d in self.doc_sink}
            for doc in docs:
                if getattr(doc, "doc_id", None) not in existing:
                    self.doc_sink.append(doc)

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

    # Pha 2 (synthesis có inline citation) — tái dùng cỗ máy của Simple. Agent (pha 1)
    # chỉ GOM nguồn vào collected_docs; các pipeline dưới đây sinh câu trả lời có 【n】.
    evidence_pipeline: PrepareEvidencePipeline = PrepareEvidencePipeline.withx()
    answering_pipeline: AnswerWithInlineCitation = AnswerWithInlineCitation.withx()
    create_citation_viz_pipeline: CreateCitationVizPipeline = Node(
        default_callback=lambda _: CreateCitationVizPipeline(
            embedding=embeddings.get_default()
        )
    )
    # Bể gom nguồn cho mỗi request (reset trong get_pipeline). Các tool docsearch/web_search
    # append nguồn vào đây qua doc_sink.
    collected_docs: list = []

    def _dedup_collected(self) -> list:
        """Khử trùng lặp nguồn đã gom theo doc_id, giữ thứ tự xuất hiện."""
        seen: set = set()
        out: list = []
        for d in self.collected_docs or []:
            key = getattr(d, "doc_id", None) or id(d)
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
        return out

    # Mỗi chunk corpus mở đầu bằng "[<Tên thủ tục> — <Phần>]" (xem pipeline/parser/parse.py).
    # Metadata KHÔNG lưu tên thủ tục nên lấy từ đây để header panel + ngữ cảnh đọc dễ hơn id file.
    _TITLE_RE = re.compile(r"^\s*\[(.+?)\]")

    def _apply_friendly_names(self, docs) -> None:
        """Đổi file_name của nguồn corpus từ id (1.001471__...md) sang tên thủ tục lấy
        từ tiền tố [Tên — Phần] trong text. Bỏ qua nguồn web (đã có nhãn 🌐 ... · web)."""
        for d in docs:
            if (getattr(d, "metadata", None) or {}).get("is_web"):
                continue
            m = self._TITLE_RE.match(getattr(d, "text", "") or "")
            if m:
                d.metadata["file_name"] = m.group(1).strip()

    # --- Các method tổng hợp/hiển thị (port từ reasoning/simple.py) ---

    def prepare_mindmap(self, answer) -> Document | None:
        mindmap = answer.metadata["mindmap"]
        if mindmap:
            mindmap_text = mindmap.text
            mindmap_svg = dedent(
                """
                <div class="markmap">
                <script type="text/template">
                ---
                markmap:
                    colorFreezeLevel: 2
                    activeNode:
                        placement: center
                    initialExpandLevel: 4
                    maxWidth: 200
                ---
                {}
                </script>
                </div>
                """
            ).format(mindmap_text)

            mindmap_content = Document(
                channel="info",
                content=Render.collapsible(
                    header="""
                    <i>Mindmap</i>
                    <a href="#" id='mindmap-toggle'>
                        [Expand]</a>
                    <a href="#" id='mindmap-export'>
                        [Export]</a>""",
                    content=mindmap_svg,
                    open=True,
                ),
            )
        else:
            mindmap_content = None

        return mindmap_content

    def prepare_citation_viz(self, answer, question, docs) -> Document | None:
        doc_texts = [doc.text for doc in docs]
        citation_plot = None
        plot_content = None

        if answer.metadata["citation_viz"] and len(docs) > 1:
            try:
                citation_plot = self.create_citation_viz_pipeline(doc_texts, question)
            except Exception as e:
                print("Failed to create citation plot:", e)

            if citation_plot:
                plot = to_json(citation_plot)
                plot_content = Document(channel="plot", content=plot)

        return plot_content

    def show_citations_and_addons(self, answer, docs, question):
        """Render nguồn trích dẫn + mindmap vào panel Information.

        Khác Simple: KHÔNG yield content=None để xoá panel, nhằm giữ lại các bước
        Thought/Action/Observation của agent (pha 1) hiển thị phía trên nguồn.
        """
        with_citation, without_citation = self.answering_pipeline.prepare_citations(
            answer, docs
        )
        mindmap_output = self.prepare_mindmap(answer)
        citation_plot_output = self.prepare_citation_viz(answer, question, docs)

        if not with_citation and not without_citation:
            yield Document(channel="info", content="<h5><b>No evidence found.</b></h5>")
            return

        max_llm_rerank_score = max(
            (doc.metadata.get("llm_trulens_score", 0.0) for doc in docs), default=0.0
        )
        has_llm_score = any("llm_trulens_score" in doc.metadata for doc in docs)
        relevance_low = (
            has_llm_score and max_llm_rerank_score < CONTEXT_RELEVANT_WARNING_SCORE
        )

        if relevance_low:
            yield Document(
                channel="info",
                content=(
                    "<h5>⚠️ Độ liên quan của nguồn thấp — câu trả lời có thể chưa "
                    "chính xác, vui lòng kiểm chứng.</h5>"
                ),
            )
        else:
            if mindmap_output:
                yield mindmap_output
            if citation_plot_output:
                yield citation_plot_output

        qa_score = (
            round(answer.metadata["qa_score"], 2)
            if answer.metadata.get("qa_score")
            else None
        )
        if qa_score:
            yield Document(
                channel="info",
                content=f"<h5>Answer confidence: {qa_score}</h5>",
            )

        # Chia rõ 2 nhóm bằng tiêu đề. Nhóm trích dẫn đã có số 【n】 trong nội dung tô sáng;
        # nhóm tham khảo được đánh số [n] riêng để dễ dẫn chiếu.
        if with_citation:
            yield Document(
                channel="info",
                content="<h4>📌 Nguồn được trích dẫn</h4>",
            )
            yield from with_citation

        if without_citation:
            yield Document(
                channel="info",
                content="<h4>📚 Nguồn tham khảo (không trích dẫn trực tiếp)</h4>",
            )
            yield from without_citation

    def prepare_citation(self, step_id, step, output, status) -> Document:
        # Header hiện "Step N: <suy luận>" để xem nhanh nội dung bước; chi tiết Action/Output
        # nằm trong content, mặc định ĐÓNG — click vào mới bung ra.
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
                open=False,
            ),
        )

    async def ainvoke(  # type: ignore
        self, message, conv_id: str, history: list, **kwargs  # type: ignore
    ) -> Document:
        # UI dùng stream() (xem pages/chat). ainvoke không qua pha citation.
        raise NotImplementedError

    def stream(self, message, conv_id: str, history: list, **kwargs):
        if self.use_rewrite:
            rewrite = self.rewrite_pipeline(question=message)
            message = rewrite.text
            yield Document(
                channel="info",
                content=f"Rewrote the message to: {rewrite.text}",
            )

        # ---- Pha 1: agent lặp Thought/Action/Observation để GOM nguồn (corpus + web) ----
        # Vẫn hiển thị từng bước vào panel Information (minh bạch quá trình agentic), nhưng
        # KHÔNG đẩy Final Answer thô của agent ra chat — câu trả lời thật do pha 2 tạo.
        output_stream = Generator(self.agent.stream(message))
        idx = 0
        agent_final_text = ""
        for item in output_stream:
            idx += 1
            # item cuối (status finished/stopped) mang Final Answer của agent — giữ lại
            # làm fallback cho trường hợp không gom được nguồn (vd chào hỏi/xã giao).
            if item.status != "thinking" and item.text:
                agent_final_text = item.text
            step, step_output = item.intermediate_steps
            yield Document(
                channel="info",
                content=self.prepare_citation(idx, step, step_output, item.status),
            )

        # ---- Pha 2: tổng hợp câu trả lời có inline citation từ các nguồn đã gom ----
        docs = self._dedup_collected()
        if not docs:
            # Không có nguồn nào: dùng Final Answer của agent (chào hỏi, hoặc lời báo
            # "không tìm thấy" của chính agent); nếu trống thì dùng câu mặc định.
            msg = agent_final_text.strip() or (
                "Chưa tìm thấy thông tin phù hợp trong cơ sở dữ liệu thủ tục hành chính "
                "cũng như trên web. Bạn vui lòng nêu cụ thể tên thủ tục để tôi tra cứu "
                "chính xác hơn."
            )
            yield Document(channel="chat", content=msg)
            return Document(content=msg)

        # Đổi id file -> tên thủ tục cho dễ đọc (header panel + ngữ cảnh synthesis).
        self._apply_friendly_names(docs)

        evidence_mode, evidence, images = self.evidence_pipeline(docs).content

        answer = yield from self.answering_pipeline.stream(
            question=message,
            history=history,
            evidence=evidence,
            evidence_mode=evidence_mode,
            images=images,
            conv_id=conv_id,
            **kwargs,
        )

        # xử lý thẻ <think> của các model reasoning (giống simple.py)
        processed_answer = replace_think_tag_with_details(answer.text)
        if processed_answer != answer.text:
            yield Document(channel="chat", content=None)
            yield Document(channel="chat", content=processed_answer)

        # Gắn ký hiệu 🌐 sau các trích dẫn trỏ về NGUỒN WEB (xác định, không phụ thuộc
        # LLM có tuân thủ chỉ dẫn prompt hay không). Dò citation->doc qua chính
        # match_evidence_with_context rồi render lại câu trả lời.
        marked = self._mark_web_citations(answer, docs)
        if marked is not None:
            yield Document(channel="chat", content=None)
            yield Document(channel="chat", content=marked)

        yield from self.show_citations_and_addons(answer, docs, message)

        return answer

    def _mark_web_citations(self, answer, docs) -> str | None:
        """Trả về câu trả lời đã gắn 🌐 sau các 【n】 trỏ về nguồn web (kèm link), hoặc
        None nếu không có trích dẫn web nào (khỏi render lại)."""
        try:
            spans = self.answering_pipeline.match_evidence_with_context(answer, docs)
        except Exception:
            return None
        id2docs = {getattr(d, "doc_id", None): d for d in docs}
        web_idxs = set()
        for doc_id, ss in spans.items():
            doc = id2docs.get(doc_id)
            if doc is not None and (doc.metadata or {}).get("is_web"):
                for s in ss:
                    if s.get("idx") is not None:
                        web_idxs.add(s["idx"])
        if not web_idxs:
            return None
        text = answer.text
        # chèn 🌐 NGAY SAU 【n】 (trước khi đổi 【n】 thành link); thứ tự giảm dần tránh
        # 【1】 khớp nhầm trong 【10】... (replace chuỗi nguyên cụm 【n】 nên đã an toàn).
        for i in sorted(web_idxs, reverse=True):
            text = text.replace(f"【{i}】", f"【{i}】🌐")
        return self.answering_pipeline.replace_citation_with_link(text)

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

        # Bể gom nguồn mới cho request này (tránh rò docs giữa các câu hỏi vì tool trong
        # TOOL_REGISTRY là singleton dùng lại). Gán cùng list vào doc_sink của các tool.
        collected: list = []
        pipeline.collected_docs = collected

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
                    tool.doc_sink = collected
                elif tool_name == "WebSearch":
                    tool.doc_sink = collected
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

        # ---- Wiring pha 2: synthesis có inline citation (giống simple.py) ----
        answer_pipeline = pipeline.answering_pipeline
        answer_pipeline.llm = llm
        answer_pipeline.citation_pipeline.llm = llm
        answer_pipeline.enable_citation = (
            settings[f"{prefix}.highlight_citation"] != "off"
        )
        answer_pipeline.enable_mindmap = settings[f"{prefix}.create_mindmap"]
        answer_pipeline.enable_citation_viz = settings[f"{prefix}.create_citation_viz"]
        answer_pipeline.system_prompt = settings[f"{prefix}.system_prompt"]
        # Prompt tổng hợp tiếng Việt + domain rules + định dạng trích dẫn (rag/prompts.py).
        answer_pipeline.qa_citation_template = REACT_QA_CITATION_PROMPT
        answer_pipeline.lang = pipeline.agent.output_lang
        answer_pipeline.n_last_interactions = settings[f"{prefix}.n_last_interactions"]

        if max_context_length_setting:
            pipeline.evidence_pipeline.max_context_length = max_context_length_setting

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
            # ---- Cấu hình pha 2 (synthesis có inline citation) — giống Simple ----
            "highlight_citation": {
                "name": "Citation style",
                "value": "inline",
                "component": "radio",
                "choices": [
                    ("citation: inline", "inline"),
                    ("no citation", "off"),
                ],
            },
            "create_mindmap": {
                "name": "Create Mindmap",
                "value": True,  # bật sơ đồ tư duy (đồng nhất với Simple); chạy nền không
                # chặn stream text, chỉ tốn thêm 1 lời gọi LLM. Bị bỏ qua khi nguồn yếu
                # (relevance_low) trong show_citations_and_addons.
                "component": "checkbox",
            },
            "create_citation_viz": {
                "name": "Create Embeddings Visualization",
                "value": False,
                "component": "checkbox",
            },
            "system_prompt": {
                "name": "System Prompt",
                "value": (
                    "Bạn là trợ lý ảo hỗ trợ tra cứu thủ tục hành chính công Việt Nam. "
                    "Luôn trả lời bằng tiếng Việt, thân thiện và chính xác. Chỉ dùng "
                    "thông tin trong ngữ cảnh, tuyệt đối không bịa đặt."
                ),
            },
            "n_last_interactions": {
                "name": "Number of interactions to include",
                "value": 5,
                "component": "number",
                "info": "The maximum number of chat interactions to include in the LLM",
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
