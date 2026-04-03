"""Gas domain expert tool — calls local fine-tuned model via vLLM (OpenAI-compatible).

When the local model is unavailable, gracefully falls back to the main LLM
with a gas-domain system prompt.
"""

import httpx
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.config import get_settings

logger = structlog.get_logger()

GAS_EXPERT_SYSTEM_PROMPT = """\
你是一位资深燃气安全专家，拥有 20 年以上城镇燃气工程和抢险经验。

## 你熟悉的规范标准
- GB 50028《城镇燃气设计规范》
- CJJ 51《城镇燃气设施运行、维护和抢修安全技术规程》
- GB/T 13611《城镇燃气分类和基本特性》
- GB 50494《城镇燃气技术规范》
- CJJ/T 153《城镇燃气管道非开挖修复更新工程技术规程》

## 回答要求
1. 基于专业知识和规范标准给出建议，注明相关规范条款编号
2. 给出具体、可操作的步骤
3. 安全建议永远放在首位
4. 区分强制性条款（"必须/应"）和推荐性条款（"宜/可"）
5. 如果信息不足以做出准确判断，主动指出需要补充的信息
"""


async def _call_local_model(query: str) -> str | None:
    """Try calling the local fine-tuned model via vLLM OpenAI-compatible endpoint."""
    settings = get_settings()
    url = f"{settings.local_model_url}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=settings.local_model_timeout) as client:
            resp = await client.post(
                url,
                json={
                    "model": settings.local_model_name,
                    "messages": [
                        {"role": "system", "content": GAS_EXPERT_SYSTEM_PROMPT},
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            logger.info("local_model_success", model=settings.local_model_name)
            return content
    except httpx.ConnectError:
        logger.info("local_model_unavailable", url=settings.local_model_url)
        return None
    except Exception as exc:
        logger.warning("local_model_error", error=str(exc))
        return None


async def _call_main_llm_as_expert(query: str) -> str:
    """Fall back to the main LLM with the gas expert system prompt."""
    from app.agent.llm import get_llm

    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content=GAS_EXPERT_SYSTEM_PROMPT),
        HumanMessage(content=query),
    ])
    logger.info("expert_fallback_to_main_llm")
    return response.content


@tool
async def consult_gas_expert(query: str) -> str:
    """咨询燃气领域专家模型，获取基于规范标准的专业回答。

    优先调用本地微调模型（vLLM），不可用时自动降级为主 LLM。

    Args:
        query: 燃气专业问题，如 "中压PE管泄漏的标准抢修流程是什么？"
    """
    result = await _call_local_model(query)
    if result is not None:
        return result

    return await _call_main_llm_as_expert(query)
