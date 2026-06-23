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
    DEFAULT_DECOMPOSE_PROMPT,
    DOCSEARCH_TOOL_DESCRIPTION,
    REACT_CONTEXTUALIZE_PROMPT,
    REACT_QA_CITATION_PROMPT,
    REACT_QA_PROMPT,
    REACT_REWRITE_PROMPT,
)
from rag.agent_tools import (  # tool dự án (rag/agent_tools.py)
    NO_RELEVANT_DOC_MESSAGE,
    REPEATED_QUERY_MESSAGE,
    BraveSearchTool,
    CitableTool,
    ToolContext,
)

from ..utils import SUPPORTED_LANGUAGE_MAP

logger = logging.getLogger(__name__)
DEFAULT_AGENT_STEPS = 4


class DocSearchArgs(BaseModel):
    query: str = Field(..., description="a search query as input to the doc search")


class DocSearchTool(CitableTool):
    name: str = "docsearch"
    description: str = DOCSEARCH_TOOL_DESCRIPTION
    args_schema: Optional[Type[BaseModel]] = DocSearchArgs
    retrievers: list[BaseComponent] = []
    # Nguồn CHÍNH THỐNG → liệt kê/dùng TRƯỚC (mục C; nhỏ = ưu tiên trước).
    priority: int = 10
    # E1 — SÀN độ liên quan: nếu điểm llm_trulens_score CAO NHẤT của lượt tra vẫn dưới
    # ngưỡng này thì coi như corpus KHÔNG có câu trả lời tin cậy (quan sát: đáp đúng
    # ~0.8–0.9, nhiễu/lạc đề ~0.2–0.3) → trả NO_RELEVANT để agent đổi truy vấn / web,
    # và KHÔNG emit (tránh synthesis bám nguồn lạc đề như hộ tịch/kiểm dịch).
    relevance_floor: float = 0.5
    # E2 — các truy vấn đã tra trong request (reset ở bind) để chặn lặp y hệt.
    seen_queries: Optional[list] = None
    # Hướng 2 — doc_id (đã qua gate) mà câu hỏi con HIỆN TẠI tra được; pipeline reset
    # trước mỗi câu con rồi so trùng giữa các câu con (collision = hai vế cùng nguồn).
    subq_doc_ids: Optional[list] = None
    # doc_sink + emit() thừa kế từ CitableTool: các đoạn liên quan được emit() vào
    # bể gom để pha synthesis tạo inline citation. None = không gom (vẫn chạy bình
    # thường cho vòng lặp agent). Pipeline gán doc_sink + retrievers qua bind().

    def bind(self, ctx: ToolContext) -> None:
        # mục A: nhận tài nguyên request-scoped thay cho gán thủ công trong get_pipeline.
        self.retrievers = ctx.retrievers
        self.doc_sink = ctx.doc_sink
        self.seen_queries = []  # E2: reset lịch sử truy vấn mỗi request

    def _run_tool(self, query: AnyStr) -> AnyStr:
        # E2 — chặn lặp truy vấn y hệt (chuẩn hoá khoảng trắng + chữ thường).
        qnorm = " ".join(str(query).lower().split())
        if self.seen_queries is None:
            self.seen_queries = []
        if qnorm in self.seen_queries:
            return Document(content=REPEATED_QUERY_MESSAGE)
        self.seen_queries.append(qnorm)

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

        # E1 — chỉ áp sàn khi scorer THỰC SỰ chạy (có llm_trulens_score); nếu scorer tắt
        # thì giữ hành vi cũ (emit hết) để không vô tình loại sạch.
        scored = [d for d in docs if "llm_trulens_score" in d.metadata]
        if scored:
            max_score = max(d.metadata["llm_trulens_score"] for d in scored)
            if max_score < self.relevance_floor:
                return Document(content=NO_RELEVANT_DOC_MESSAGE)

        # mục B: gom các đoạn liên quan (đã có llm_trulens_score) cho pha synthesis
        # qua emit() — tự dedup theo doc_id, dùng chung cơ chế với mọi citable tool.
        for doc in docs:
            self.emit(doc)

        # Hướng 2: ghi định danh THỦ TỤC (file nguồn) cho câu hỏi con hiện tại — KHÔNG
        # dùng doc_id chunk-level (hai câu con cùng thủ tục vẫn ra chunk khác nhau → trùng
        # thấp giả). file_name lúc này là id .md, dùng chung cho mọi chunk của một thủ tục.
        if self.subq_doc_ids is not None:
            self.subq_doc_ids.extend(
                (d.metadata or {}).get("file_name") for d in docs
            )

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
                # GIỮ \n (không gộp thành space): vừa để panel Suy luận dựng được bảng
                # markdown qua table_or_linebreaks, vừa cho LLM ngữ cảnh có cấu trúc hơn.
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

def _bind_tool(tool, ctx: ToolContext) -> None:
    """Tiêm tài nguyên request-scoped vào tool (mục A — thay cho switch theo tên).

    Tool dự án (CitableTool) tự khai báo nhu cầu qua bind(). Tool thư viện
    (LLMTool, Google, Wikipedia...) không kế thừa CitableTool → duck-typing tối
    thiểu cho `llm`, KHÔNG rẽ nhánh theo tên tool.
    """
    if isinstance(tool, CitableTool):
        tool.bind(ctx)
    elif ctx.llm is not None and hasattr(tool, "llm"):
        tool.llm = ctx.llm


# Prompt tiếng Việt + domain rules — định nghĩa trong rag/prompts.py (xem import ở đầu file)
DEFAULT_QA_PROMPT = REACT_QA_PROMPT
DEFAULT_REWRITE_PROMPT = REACT_REWRITE_PROMPT
DEFAULT_CONTEXTUALIZE_PROMPT = REACT_CONTEXTUALIZE_PROMPT


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


class ContextualizeQuestionPipeline(BaseComponent):
    """Viết lại câu hỏi follow-up thành câu hỏi ĐỘC LẬP dựa trên lịch sử hội thoại.

    Giải tham chiếu ngầm ('thủ tục này', 'nó', 'cơ quan ấy'...). BẮT BUỘC cho RAG hội
    thoại đa lượt: pha 1 (ReactAgent gom nguồn) là STATELESS với history — nếu không
    contextualize, truy vấn follow-up mất ngữ cảnh và retrieve lạc chủ đề (vd hỏi tiếp
    về 'cơ quan thực hiện' sau câu hỏi hộ chiếu lại ra thủ tục đất đai).

    Chỉ chạy khi CÓ history; lượt đầu (history rỗng) trả nguyên câu hỏi, không gọi LLM.
    """

    llm: ChatLLM = Node(default_callback=lambda _: llms.get_default())
    contextualize_template: str = DEFAULT_CONTEXTUALIZE_PROMPT
    lang: str = "English"
    n_last_interactions: int = 5

    def run(self, question: str, history: list) -> Document:  # type: ignore
        if not history:
            return Document(text=question)
        chat_history = "\n".join(
            f"Người dùng: {human}\nTrợ lý: {ai}"
            for human, ai in history[-self.n_last_interactions :]
        )
        prompt = PromptTemplate(self.contextualize_template).populate(
            chat_history=chat_history,
            question=question,
            lang=self.lang,
        )
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content=prompt),
        ]
        return self.llm(messages)


class DecomposeQuestionPipeline(BaseComponent):
    """Phase-0 (Hướng 1): tách câu hỏi phức thành các câu hỏi con độc lập.

    Chạy SAU contextualize, TRƯỚC vòng lặp agent. Pipeline sẽ fan-out: chạy vòng
    lặp agent cho TỪNG câu hỏi con (dồn nguồn vào chung collected_docs) để phủ hết
    khía cạnh — thay cho việc dặn agent tự tách bằng prompt (không tin cậy). Câu
    hỏi đơn → trả 1 dòng = câu gốc → pipeline chạy y như trước (không tốn fan-out).

    Theo pattern RewriteQuestionPipeline (return self.llm(messages)) cho an toàn với
    theflow; pipeline parse text trả về thành list ở _plan_subquestions.
    """

    llm: ChatLLM = Node(default_callback=lambda _: llms.get_default())
    decompose_template: str = DEFAULT_DECOMPOSE_PROMPT

    def run(self, question: str) -> Document:  # type: ignore
        prompt = PromptTemplate(self.decompose_template).populate(question=question)
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
    # Contextualize câu hỏi follow-up bằng history TRƯỚC pha 1 (xem class trên).
    contextualize_pipeline: ContextualizeQuestionPipeline = (
        ContextualizeQuestionPipeline.withx()
    )
    # Phase-0 (Hướng 1): tách câu hỏi phức rồi fan-out vòng lặp agent theo từng câu con.
    decompose_pipeline: DecomposeQuestionPipeline = DecomposeQuestionPipeline.withx()
    use_decompose: bool = True
    max_sub_questions: int = 4  # trần fan-out (chống bùng nổ vòng lặp + token)
    # Gom & tổng hợp theo THỦ TỤC (Fix 1): sau fan-out, nhóm nguồn theo từng thủ tục
    # (file_id) rồi KÉO ĐỦ mọi phần (hồ sơ/trình tự/thời gian/phí) của các thủ tục đủ
    # tin cậy từ docstore — để synthesis có dữ liệu đầy đủ cho TỪNG thủ tục và trình bày
    # tách bạch (không gộp Frankenstein). Chỉ MỞ RỘNG thủ tục mạnh (điểm cao), trong hạn
    # mức; KHÔNG loại thủ tục yếu (việc đó thuộc Fix 2 — không bật) nên không khuếch đại
    # nguồn lạc.
    expand_full_procedures: bool = True
    full_procedure_threshold: float = 0.6  # điểm tối thiểu để được kéo đủ phần
    max_full_procedures: int = 4  # trần số thủ tục kéo đủ (chống phình context)

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

    def _plan_subquestions(self, question: str) -> list:
        """Hướng 1: gọi planner tách câu hỏi → list câu con. Câu đơn (hoặc planner
        lỗi) trả [question] để pipeline chạy đúng như trước. Dedup gần trùng + cap."""
        if not self.use_decompose:
            return [question]
        try:
            resp = self.decompose_pipeline(question=question)
            text = (resp.text or "")
        except Exception:
            return [question]
        subs: list = []
        seen: set = set()
        for ln in text.splitlines():
            ln = ln.strip(" -•\t").strip()
            if len(ln) < 6:  # bỏ dòng rác/đánh số trống
                continue
            key = " ".join(ln.lower().split())
            if key in seen:
                continue
            seen.add(key)
            subs.append(ln)
            if len(subs) >= self.max_sub_questions:
                break
        # Nếu planner chỉ trả 1 câu (hoặc trùng hệt câu gốc) → coi như câu đơn.
        return subs or [question]

    @staticmethod
    def _collision_notes(sub_questions: list, subq_sets: dict) -> list:
        """Hướng 2 (deterministic): tìm các cặp câu hỏi con thật sự hỏi về CÙNG MỘT
        thủ tục dưới hai cách diễn đạt khác nhau (so sánh giả của một thứ).

        Fix 3 — THU HẸP: chỉ kích hoạt khi hai câu con cùng trỏ về ĐÚNG MỘT thủ tục
        GIỐNG HỆT (sa == sb và |sa| == 1). Trước đây dùng Jaccard ≥ 0.6: chỉ cần trùng
        nhiều là ép synthesis 'trình bày như cùng một loại' — điều này VÔ TÌNH gộp các
        thủ tục THẬT SỰ KHÁC NHAU (vd 'thành lập' vs 'cho phép hoạt động' cùng xuất hiện
        ở nhiều câu con). Khi đã nhóm theo thủ tục (Fix 1), chỉ giữ note cho trường hợp
        một-thủ-tục-hai-cách-hỏi để tránh đè lên câu trả lời đa thủ tục."""
        keys = sorted(subq_sets)
        pairs = []
        for ai in range(len(keys)):
            for bi in range(ai + 1, len(keys)):
                sa, sb = subq_sets[keys[ai]], subq_sets[keys[bi]]
                if not sa or not sb:
                    continue
                if sa == sb and len(sa) == 1:
                    pairs.append((sub_questions[keys[ai] - 1], sub_questions[keys[bi] - 1]))
        if not pairs:
            return []
        ps = "; ".join(f"«{a}» và «{b}»" for a, b in pairs)
        return [
            f"Các phần sau của câu hỏi cùng trỏ về MỘT bộ tài liệu giống nhau, nguồn "
            f"KHÔNG phân biệt chúng: {ps}. Hãy trình bày như cùng một loại, không tạo "
            f"các mục riêng lặp lại cùng nội dung dưới những nhãn khác nhau."
        ]

    def _dedup_collected(self) -> list:
        """Khử trùng lặp nguồn đã gom theo doc_id, giữ thứ tự xuất hiện.

        Sau khi pha 2 đã gom & tổng hợp theo thủ tục (_assemble_by_procedure), trả
        thẳng kết quả đã assemble để engine.build_citations khớp citation trên CÙNG
        bộ tài liệu mà synthesis nhìn thấy (gồm cả phần kéo thêm từ docstore)."""
        if getattr(self, "_assembled_docs", None) is not None:
            return self._assembled_docs
        seen: set = set()
        out: list = []
        for d in self.collected_docs or []:
            key = getattr(d, "doc_id", None) or id(d)
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
        return out

    def _full_procedure_docs(self, file_id: str) -> list:
        """Lấy TẤT CẢ chunk (mọi phần) của một thủ tục từ docstore theo source_id.

        Map thủ tục→chunk qua bảng Index (relation_type='document', source_id=file_id)
        rồi DS.get(chunk_ids). Trả [] nếu không truy được (vd nguồn web). Giữ thứ tự
        chunk = thứ tự tài liệu gốc (Index trả theo thứ tự ingest)."""
        if not file_id:
            return []
        from ktem.db.models import engine
        from sqlmodel import Session, select

        for r in self.retrievers:
            Index = getattr(r, "Index", None)
            DS = getattr(r, "DS", None)
            if Index is None or DS is None:
                continue
            try:
                with Session(engine) as s:
                    rows = s.exec(
                        select(Index.target_id).where(
                            Index.relation_type == "document",
                            Index.source_id == file_id,
                        )
                    ).all()
                chunk_ids = [x[0] if isinstance(x, tuple) else x for x in rows]
                if not chunk_ids:
                    continue
                got = DS.get(chunk_ids)
                if got:
                    return list(got)
            except Exception:
                continue
        return []

    @staticmethod
    def _merge_sections(gated: list, full: list) -> list:
        """Hợp nhất chunk đã gate (mang điểm relevance) với toàn bộ phần kéo từ docstore.

        Giữ thứ tự tài liệu (theo `full`); chép llm_trulens_score từ chunk đã gate sang
        chunk tương ứng để gate/citation nhất quán; thêm chunk đã gate không có trong
        full (hiếm) vào cuối."""
        by_id: dict = {}
        order: list = []
        for d in full:
            did = getattr(d, "doc_id", None)
            by_id[did] = d
            order.append(did)
        for d in gated:
            did = getattr(d, "doc_id", None)
            if did in by_id:
                sc = (getattr(d, "metadata", None) or {}).get("llm_trulens_score")
                if sc is not None:
                    by_id[did].metadata["llm_trulens_score"] = sc
            else:
                by_id[did] = d
                order.append(did)
        return [by_id[i] for i in order]

    def _assemble_by_procedure(self, docs: list) -> list:
        """Fix 1: nhóm nguồn theo THỦ TỤC (file_id) → xếp thủ tục theo điểm giảm dần →
        với thủ tục đủ mạnh (trong hạn mức) KÉO ĐỦ mọi phần từ docstore. Trả list phẳng,
        các chunk của cùng một thủ tục NẰM LIỀN NHAU → PrepareEvidencePipeline dựng
        evidence có ranh giới thủ tục rõ (nhãn 'Content from <tên thủ tục>'), synthesis
        tự trình bày tách bạch. Nguồn web giữ nguyên, xếp cuối."""
        groups: dict = {}  # file_id -> {"file_id", "chunks":[], "score":float, "ord":int}
        web: list = []
        for d in docs:
            m = getattr(d, "metadata", None) or {}
            if m.get("is_web"):
                web.append(d)
                continue
            fid = m.get("file_id") or m.get("file_name")
            g = groups.get(fid)
            if g is None:
                g = {"file_id": m.get("file_id"), "chunks": [], "score": 0.0,
                     "ord": len(groups)}
                groups[fid] = g
            g["chunks"].append(d)
            g["score"] = max(g["score"], m.get("llm_trulens_score", 0.0) or 0.0)

        # Thủ tục mạnh trước; giữ thứ tự xuất hiện cho các thủ tục cùng điểm (ổn định).
        ranked = sorted(groups.values(), key=lambda g: (-g["score"], g["ord"]))

        out: list = []
        expanded = 0
        for g in ranked:
            chunks = g["chunks"]
            if (
                self.expand_full_procedures
                and g["file_id"]
                and g["score"] >= self.full_procedure_threshold
                and expanded < self.max_full_procedures
            ):
                full = self._full_procedure_docs(g["file_id"])
                if full:
                    chunks = self._merge_sections(chunks, full)
                    expanded += 1
            out.extend(chunks)
        out.extend(web)
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

    def prepare_citation(self, step_id, step, output, status, header_prefix="") -> Document:
        # Tiêu đề GỌN: "Bước N" (+ tên tool nếu đang gọi tool). header_prefix gắn nhãn
        # câu hỏi con khi đã fan-out (vd "[2/3] "). Chi tiết nằm trong content, mặc định
        # ĐÓNG — click mới bung ra.
        is_thinking = status == "thinking"
        header = "{p}<b>Bước {id}</b>".format(p=header_prefix, id=step_id)
        if is_thinking and step.tool:
            header += " · <i>{tool}</i>".format(tool=step.tool)

        parts = []
        # Suy nghĩ/Action của agent (step.log đã chứa "Action/Action Input"); giữ xuống dòng.
        log = (step.log or "").strip()
        if log:
            parts.append(Render.table_or_linebreaks(log))
        # Output (Observation) render RIÊNG bằng table_or_linebreaks → dựng bảng markdown +
        # giữ xuống dòng. KHÔNG gộp chung vào một Render.table (sẽ nuốt \n, làm hỏng bảng).
        out = output if is_thinking else "Finished"
        parts.append("<p><b>Output</b>:</p>" + Render.table_or_linebreaks(out))

        return Document(
            channel="info",
            content=Render.collapsible(
                header=header,
                content="".join(parts),
                open=False,
            ),
        )

    async def ainvoke(  # type: ignore
        self, message, conv_id: str, history: list, **kwargs  # type: ignore
    ) -> Document:
        # UI dùng stream() (xem pages/chat). ainvoke không qua pha citation.
        raise NotImplementedError

    def stream(self, message, conv_id: str, history: list, **kwargs):
        # Reset kết quả assemble của request trước (xem _assemble_by_procedure +
        # _dedup_collected). collected_docs đã được reset ở get_pipeline.
        self._assembled_docs = None
        # ---- Contextualize: giải tham chiếu ngầm của câu hỏi follow-up bằng history,
        # TRƯỚC khi agent (pha 1) gom nguồn — vì agent stateless với history. Chỉ chạy
        # khi CÓ history (lượt thứ 2 trở đi); lượt đầu giữ nguyên, không tốn lời gọi LLM.
        # Cả pha 1 (retrieve) lẫn pha 2 (synthesis) dùng chung câu đã contextualize để
        # nhất quán; pha 2 vẫn nhận history nên không mất giọng hội thoại.
        if history:
            contextualized = self.contextualize_pipeline(
                question=message, history=history
            )
            standalone = (contextualized.text or "").strip()
            if standalone and standalone != message:
                message = standalone
                yield Document(
                    channel="info",
                    content=f"Đã bổ sung ngữ cảnh cho truy vấn: {standalone}",
                )

        if self.use_rewrite:
            rewrite = self.rewrite_pipeline(question=message)
            message = rewrite.text
            yield Document(
                channel="info",
                content=f"Rewrote the message to: {rewrite.text}",
            )

        # ---- Phase-0 (Hướng 1): tách câu hỏi phức thành các câu hỏi con ----
        sub_questions = self._plan_subquestions(message)
        multi = len(sub_questions) > 1
        if multi:
            yield Document(
                channel="info",
                content=(
                    f"Đã tách câu hỏi thành {len(sub_questions)} phần để tra cứu đầy đủ: "
                    + "; ".join(sub_questions)
                ),
            )
            # Mỗi câu con ATOMIC nên cần ít vòng hơn; chia ngân sách vòng lặp để tổng số
            # lời gọi LLM không bùng nổ (trần ~ max_iterations ban đầu).
            self.agent.max_iterations = max(2, self.agent.max_iterations // len(sub_questions))

        # ---- Pha 1: với TỪNG câu hỏi con, agent lặp Thought/Action/Observation để GOM
        # nguồn (corpus + web). Nguồn dồn vào CHUNG collected_docs (sink không reset giữa
        # các câu con); seen_queries của docsearch cũng giữ → không tra trùng xuyên câu con.
        # KHÔNG đẩy Final Answer thô của agent ra chat — câu trả lời thật do pha 2 tạo.
        # Hướng 2: tham chiếu docsearch tool để chụp tập doc_id theo từng câu con.
        ds_tool = next(
            (t for t in self.agent.plugins if getattr(t, "name", "") == "docsearch"),
            None,
        )
        subq_sets: dict = {}

        idx = 0
        agent_final_text = ""
        for sq_i, sub_q in enumerate(sub_questions, 1):
            prefix = f"[{sq_i}/{len(sub_questions)}] " if multi else ""
            if ds_tool is not None:
                ds_tool.subq_doc_ids = []  # reset bộ đếm doc_id cho câu con này
            output_stream = Generator(self.agent.stream(sub_q))
            for item in output_stream:
                idx += 1
                # item cuối (finished/stopped) mang Final Answer của agent — giữ lại làm
                # fallback khi không gom được nguồn (vd chào hỏi/xã giao).
                if item.status != "thinking" and item.text:
                    agent_final_text = item.text
                step, step_output = item.intermediate_steps
                yield Document(
                    channel="info",
                    content=self.prepare_citation(
                        idx, step, step_output, item.status, header_prefix=prefix
                    ),
                )
            if multi and ds_tool is not None:
                subq_sets[sq_i] = {x for x in (ds_tool.subq_doc_ids or []) if x}

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

        # Fix 1: nhóm theo thủ tục + kéo đủ phần của thủ tục mạnh từ docstore, để pha 2
        # có dữ liệu đầy đủ cho TỪNG thủ tục và trình bày tách bạch. Lưu lại để
        # _dedup_collected (engine.build_citations) khớp trên cùng bộ tài liệu.
        docs = self._assemble_by_procedure(docs)
        self._assembled_docs = docs

        # Đổi id file -> tên thủ tục cho dễ đọc (header panel + ngữ cảnh synthesis).
        self._apply_friendly_names(docs)

        evidence_mode, evidence, images = self.evidence_pipeline(docs).content

        # ---- Hướng 2 (deterministic): chống so sánh giả do fan-out tạo ra ----
        # Fix 3 — chỉ khi hai câu hỏi con cùng trỏ về ĐÚNG MỘT thủ tục giống hệt (một
        # thủ tục được hỏi theo hai cách) → chèn ghi chú để synthesis không bịa hai mục
        # riêng cho cùng một thứ. KHÔNG còn kích hoạt khi các câu con chạm nhiều thủ tục
        # khác nhau (tránh ép gộp các thủ tục thật sự khác). Chỉ chạy khi đã fan-out.
        if multi:
            notes = self._collision_notes(sub_questions, subq_sets)
            if notes:
                for n in notes:
                    yield Document(channel="info", content=f"🔎 Kiểm chứng nguồn: {n}")
                evidence = (
                    "[CHỈ DẪN HỆ THỐNG — không trích dẫn dòng này] "
                    + " ".join(notes)
                    + "\n\n"
                    + evidence
                )

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
        # TOOL_REGISTRY là singleton dùng lại).
        collected: list = []
        pipeline.collected_docs = collected

        # mục A: tiêm tài nguyên request-scoped MỘT lần; mỗi tool tự lấy thứ cần
        # trong bind() → không còn switch theo tên tool ở đây.
        ctx = ToolContext(retrievers=retrievers, llm=llm, doc_sink=collected)

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
                _bind_tool(tool, ctx)
                tools.append(tool)
        # mục C: liệt kê tool theo priority (nhỏ = ưu tiên trước) — thứ tự này quyết
        # định thứ tự xuất hiện trong tool_description/tool_names của prompt điều phối.
        pipeline.agent.plugins = sorted(
            tools, key=lambda t: getattr(t, "priority", 100)
        )
        pipeline.agent.output_lang = SUPPORTED_LANGUAGE_MAP.get(
            settings["reasoning.lang"], "English"
        )
        pipeline.rewrite_pipeline.lang = pipeline.agent.output_lang
        pipeline.use_rewrite = states.get("app", {}).get("regen", False)
        # Contextualize follow-up dùng cùng LLM/ngôn ngữ; số lượt history lấy theo cấu
        # hình n_last_interactions của synthesis cho nhất quán.
        pipeline.contextualize_pipeline.llm = llm
        pipeline.contextualize_pipeline.lang = pipeline.agent.output_lang
        pipeline.contextualize_pipeline.n_last_interactions = settings[
            f"{prefix}.n_last_interactions"
        ]
        # Phase-0 planner (Hướng 1) dùng cùng LLM.
        pipeline.decompose_pipeline.llm = llm
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
