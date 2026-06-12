import logging
from textwrap import dedent

from ktem.llms.manager import llms

from kotaemon.base import BaseComponent, Document, HumanMessage, Node, SystemMessage
from kotaemon.llms import ChatLLM, PromptTemplate

from rag.prompts import (  # prompt tiếng Việt của dự án (rag/prompts.py)
    MINDMAP_PROMPT_TEMPLATE as VI_MINDMAP_PROMPT_TEMPLATE,
    MINDMAP_SYSTEM_PROMPT as VI_MINDMAP_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


MINDMAP_HTML_EXPORT_TEMPLATE = dedent(
    """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Mindmap</title>
    <style>
      svg.markmap {
        width: 100%;
        height: 100vh;
      }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.16"></script>
  </head>
  <body>
    {markmap_div}
  </body>
</html>
"""
)


class CreateMindmapPipeline(BaseComponent):
    """Create a mindmap from the question and context"""

    llm: ChatLLM = Node(default_callback=lambda _: llms.get_default())

    # Prompt tiếng Việt + tinh chỉnh domain — định nghĩa ở rag/prompts.py (xem import đầu
    # file). Giữ token @startmindmap/@endmindmap + dấu '*' để convert_uml_to_markdown parse.
    SYSTEM_PROMPT = VI_MINDMAP_SYSTEM_PROMPT
    MINDMAP_PROMPT_TEMPLATE = VI_MINDMAP_PROMPT_TEMPLATE
    prompt_template: str = MINDMAP_PROMPT_TEMPLATE

    @classmethod
    def convert_uml_to_markdown(cls, text: str) -> str:
        start_phrase = "@startmindmap"
        end_phrase = "@endmindmap"

        try:
            text = text.split(start_phrase)[-1]
            text = text.split(end_phrase)[0]
            text = text.strip().replace("*", "#")
        except IndexError:
            text = ""

        return text

    def run(self, question: str, context: str) -> Document:  # type: ignore
        prompt_template = PromptTemplate(self.prompt_template)
        prompt = prompt_template.populate(
            question=question,
            context=context,
        )

        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        uml_text = self.llm(messages).text
        markdown_text = self.convert_uml_to_markdown(uml_text)

        # Log quy trình để kiểm tra (trước đây luồng mindmap hoàn toàn im lặng): UML thô
        # do LLM sinh + markdown sau chuyển đổi. Dùng print() (KHÔNG logger.info) cho đồng
        # nhất với phần còn lại của pipeline — app không cấu hình logging nên logger.info bị
        # mức WARNING mặc định của Python nuốt mất. Cảnh báo riêng khi parse ra rỗng (LLM
        # trả sai định dạng → convert_uml_to_markdown nuốt IndexError trả "").
        print("[mindmap] UML thô từ LLM:\n" + uml_text)
        if markdown_text:
            print("[mindmap] Markdown sau chuyển đổi:\n" + markdown_text)
        else:
            print(
                "[mindmap] Markdown RỖNG — LLM không trả đúng @startmindmap/@endmindmap. "
                "UML thô: " + repr(uml_text)
            )

        return Document(
            text=markdown_text,
        )
