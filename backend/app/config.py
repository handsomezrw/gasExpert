from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    local_model_url: str = "http://localhost:8000/v1"
    local_model_name: str = "gas-expert"
    local_model_timeout: float = 30.0

    # QWeather: 控制台「设置」中的专属 API Host，如 https://xxxx.qweatherapi.com（公用 devapi/geoapi 已逐步停用）
    weather_api_host: str = "https://n55u9wu8j9.re.qweatherapi.com"
    weather_api_key: str = "9c62fea6c82a42688dd440f2cdd1f860"

    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    database_url: str = "sqlite+aiosqlite:///./data/copilot.db"
    chroma_persist_dir: str = "./data/chroma"

    rag_collection_name: str = "gas_regulations"
    rag_chunks_path: str = "./data/rag_chunks.json"
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 100
    rag_vector_top_k: int = 20
    rag_bm25_top_k: int = 20
    rag_final_top_k: int = 5
    rag_enable_reranker: bool = False
    rag_use_hyde: bool = False

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "gas-copilot"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
