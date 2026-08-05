import json
import logging
import os
import typing
from typing import Any, Iterable, Literal

import boto3
from dotenv import load_dotenv
from pydantic import BaseModel

from graphiti_core import Graphiti
from graphiti_core.driver.neptune_driver import NeptuneDriver
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client.client import LLMClient, get_extraction_language_instruction
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.errors import RateLimitError

load_dotenv()

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
BEDROCK_EMBEDDING_MODEL_ID = os.getenv(
    "BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
)

logger = logging.getLogger(__name__)


def _parse_endpoint(endpoint: str) -> str:
    """Strip protocol prefixes from endpoint strings for consistent handling.

    Accepts: hostname, https://hostname, neptune-db://hostname
    Returns: just the hostname
    """
    if not endpoint:
        return endpoint
    for prefix in ("neptune-db://", "neptune-graph://", "https://"):
        if endpoint.startswith(prefix):
            return endpoint[len(prefix):]
    return endpoint


# --- Monkey-patch NeptuneDriver at the class level ---
# Neptune Database's execute_open_cypher_query rejects queries with parameters
# that are not referenced in the query string OR have None values.
# graphiti_core's _sanitize_parameters can inline datetime values (removing $param)
# without removing the param from the dict. It also conditionally builds query clauses
# but unconditionally passes all params.
# This patch strips unreferenced and None-valued params after sanitization.
import re as _re

_original_run_query = NeptuneDriver._run_query


def _patched_run_query(self, cypher_query_, params):
    # Handle nested 'params' dict: search_utils.py passes params=filter_params as a kwarg,
    # which creates {'params': {'group_ids': [...]}, 'search_vector': [...], ...}.
    # Flatten by merging the nested 'params' dict into the top level.
    if 'params' in params and isinstance(params['params'], dict):
        nested = params.pop('params')
        params.update(nested)

    cypher_query_ = str(self._sanitize_parameters(cypher_query_, params))
    if params:
        referenced = set(_re.findall(r'\$(\w+)', cypher_query_))
        params = {k: v for k, v in params.items() if k in referenced and v is not None}
    try:
        result = self.client.query(cypher_query_, params=params)
    except Exception as e:
        logger.error('Query: %s', cypher_query_)
        logger.error('Parameters: %s', params)
        logger.error('Error executing query: %s', e)
        raise e
    return result, None, None


NeptuneDriver._run_query = _patched_run_query


class LiteLLMClient(LLMClient):
    """LLM client for Graphiti that uses litellm to call Amazon Bedrock.

    litellm handles the Bedrock auth (SigV4) natively via boto3 — no tokens or
    OpenAI-compatible endpoints needed.  Model IDs use litellm's 'bedrock/' prefix.
    """

    StructuredOutputMode = Literal['json_schema', 'json_object']

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        max_tokens: int = 16384,
        structured_output_mode: StructuredOutputMode = 'json_object',
    ):
        if config is None:
            config = LLMConfig()
        super().__init__(config, cache)
        self.max_tokens = max_tokens
        self.structured_output_mode = structured_output_mode

    async def _generate_response(
        self,
        messages: list,
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        import litellm

        litellm_messages = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                litellm_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                litellm_messages.append({'role': 'system', 'content': m.content})

        # Use bedrock/ prefix for litellm routing
        model = f"bedrock/{self.model}" if not self.model.startswith("bedrock/") else self.model

        kwargs: dict[str, Any] = {
            'model': model,
            'messages': litellm_messages,
            'temperature': self.temperature,
            'max_tokens': max_tokens,
        }

        # Request JSON output
        if response_model is not None:
            kwargs['response_format'] = {'type': 'json_object'}
            # Inject schema into prompt for guidance
            serialized_model = json.dumps(response_model.model_json_schema())
            litellm_messages[-1]['content'] += (
                f'\n\nRespond with a JSON object in the following format:\n\n{serialized_model}'
            )

        try:
            response = await litellm.acompletion(**kwargs)
            result = response.choices[0].message.content or ''
            if not result:
                from graphiti_core.llm_client.errors import EmptyResponseError
                raise EmptyResponseError('LLM returned an empty response')
            # Strip markdown code fences if present
            stripped = result.strip()
            if stripped.startswith('```'):
                import re
                stripped = re.sub(r'^```[a-zA-Z0-9_-]*[ \t]*\r?\n?', '', stripped)
                stripped = re.sub(r'\r?\n?```[ \t]*$', '', stripped)
                stripped = stripped.strip()
            return json.loads(stripped)
        except Exception as e:
            if 'rate' in str(e).lower():
                raise RateLimitError from e
            logger.error(f'Error in generating LLM response: {e}')
            raise

    async def generate_response(
        self,
        messages: list,
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
        group_id: str | None = None,
        prompt_name: str | None = None,
        *,
        attribute_extraction: bool = False,
    ) -> dict[str, typing.Any]:
        self._apply_attribute_extraction_preamble(messages, attribute_extraction)
        if max_tokens is None:
            max_tokens = self.max_tokens

        # Add multilingual extraction instructions
        messages[0].content += get_extraction_language_instruction(group_id)

        with self.tracer.start_span('llm.generate') as span:
            attributes = {
                'llm.provider': 'bedrock',
                'model.size': model_size.value,
                'max_tokens': max_tokens,
            }
            if prompt_name:
                attributes['prompt.name'] = prompt_name
            span.add_attributes(attributes)

            try:
                return await self._generate_response_with_retry(
                    messages, response_model, max_tokens=max_tokens, model_size=model_size
                )
            except Exception as e:
                span.set_status('error', str(e))
                span.record_exception(e)
                raise


class BedrockEmbedder(EmbedderClient):
    """Embedder that uses Amazon Bedrock's Titan Text Embeddings model via InvokeModel.

    Uses the standard AWS credential chain — no API key needed.
    """

    def __init__(self, model_id: str = None, region: str = None, dimensions: int = 1024):
        session = boto3.Session()
        self.region = region or session.region_name or "us-east-1"
        self.model_id = model_id or BEDROCK_EMBEDDING_MODEL_ID
        self.dimensions = dimensions
        self.client = session.client("bedrock-runtime", region_name=self.region)

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        """Generate embeddings for a single text input."""
        if isinstance(input_data, list):
            # If given a list, embed the first item (Graphiti calls create per-item)
            text = input_data[0] if input_data else ""
        else:
            text = str(input_data)

        body = json.dumps({
            "inputText": text,
            "dimensions": self.dimensions,
            "normalize": True,
        })

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        embeddings = []
        for text in input_data_list:
            embedding = await self.create(text)
            embeddings.append(embedding)
        return embeddings


class GraphitiDemo:
    """Wrapper over Graphiti for graph-based memory using Amazon Neptune
    with Amazon Bedrock as the LLM and embedding provider.

    Required environment variables:
        GRAPHITI_NEPTUNE_ENDPOINT - Neptune Database endpoint
        GRAPHITI_AOSS_ENDPOINT - OpenSearch Serverless endpoint for vector search
        AWS_REGION (or boto3 default region) - AWS region for Bedrock calls

    Optional environment variables:
        BEDROCK_MODEL_ID - LLM model (defaults to Claude Sonnet 4)
        BEDROCK_EMBEDDING_MODEL_ID - Embedding model (defaults to Titan Embed V2)
        GRAPHITI_NEPTUNE_PORT - Neptune port (defaults to 8182)

    Authentication uses the standard AWS credential chain (no API keys needed).
    """

    def __init__(self, group_id: str):
        neptune_uri = os.environ.get("GRAPHITI_NEPTUNE_ENDPOINT", "")
        aoss_host = _parse_endpoint(os.environ.get("GRAPHITI_AOSS_ENDPOINT", ""))

        if not neptune_uri:
            raise ValueError("GRAPHITI_NEPTUNE_ENDPOINT must be set")

        if not aoss_host:
            raise ValueError("GRAPHITI_AOSS_ENDPOINT must be set")

        # Set up Neptune graph driver
        self.driver = NeptuneDriver(
            host=neptune_uri,
            port=int(os.environ.get("GRAPHITI_NEPTUNE_PORT", 8182)),
            aoss_host=aoss_host,
        )
        # Increase AOSS timeout to handle serverless cold starts (default is 10s)
        self.driver.aoss_client.transport.kwargs['timeout'] = 30
        # Workaround: graphiti_core 0.29.x expects _database on all drivers
        # but NeptuneDriver doesn't set it. Default to empty string.
        if not hasattr(self.driver, '_database'):
            self.driver._database = ""

        # Configure Graphiti to use Bedrock via litellm (no token/mantle needed)
        llm_config = LLMConfig(
            api_key="unused",  # litellm uses boto3 credential chain
            model=BEDROCK_MODEL_ID,
            small_model=BEDROCK_MODEL_ID,
        )
        llm_client = LiteLLMClient(
            config=llm_config,
            structured_output_mode="json_object",
        )

        # Use Bedrock Titan for embeddings
        session = boto3.Session()
        region = session.region_name or "us-east-1"
        embedder = BedrockEmbedder(region=region)

        # Use the LLM-based reranker via litellm
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

        cross_encoder = OpenAIRerankerClient(
            client=llm_client,
            config=llm_config,
        )

        self.client = Graphiti(
            graph_driver=self.driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )
        self.group_id = group_id

    async def reset(self):
        await self.driver.delete_aoss_indices()
        await self.driver._delete_all_data()
        await self.client.build_indices_and_constraints()
