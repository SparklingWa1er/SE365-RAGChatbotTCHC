import logging

from ktem.llms.manager import llms

from kotaemon.base import AIMessage, BaseComponent, Document, HumanMessage, Node
from kotaemon.llms import ChatLLM, PromptTemplate

logger = logging.getLogger(__name__)


class SuggestFollowupQuesPipeline(BaseComponent):
    """Suggest a list of follow-up questions based on the chat history."""

    llm: ChatLLM = Node(default_callback=lambda _: llms.get_default())
    SUGGEST_QUESTIONS_PROMPT_TEMPLATE = (
        "Based on the chat history above, generate 3 to 5 relevant follow-up "
        "questions that THE USER would naturally ask the assistant next. "
        "Write each question from the user's point of view (the user is asking, "
        "the assistant answers) — do NOT phrase them as the assistant asking the "
        "user. The questions must be simple, very concise, and continue the same "
        "topic. Respond in JSON format with 'questions' key. "
        "Answer using the language {lang} same as the question. "
    )
    prompt_template: str = SUGGEST_QUESTIONS_PROMPT_TEMPLATE
    extra_prompt: str = """Example of valid response (note: questions are asked BY the user TO the assistant):
```json
{
    "questions": ["Lệ phí cấp hộ chiếu là bao nhiêu?", "Còn các loại hộ chiếu nào khác?"]
}
```"""
    lang: str = "English"

    def run(self, chat_history: list[tuple[str, str]]) -> Document:
        prompt_template = PromptTemplate(self.prompt_template)
        prompt = prompt_template.populate(lang=self.lang) + self.extra_prompt

        messages = []
        for human, ai in chat_history[-3:]:
            messages.append(HumanMessage(content=human))
            messages.append(AIMessage(content=ai))

        messages.append(HumanMessage(content=prompt))

        return self.llm(messages)
