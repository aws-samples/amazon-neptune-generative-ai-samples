import tiktoken
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.core import Settings
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding

# Setup the llm to use Bedrock and the provided model name
llm = Bedrock(model="anthropic.claude-3-sonnet-20240229-v1:0", temperature=0)
Settings.llm = llm
# Setup the embedding model to use Bedrock and the provided model name
embed_model = BedrockEmbedding(
    model_name="amazon.titan-embed-text-v2:0", additional_kwargs={"dimensions": 256}
)
Settings.embed_model = embed_model

# you can set a tokenizer directly, or optionally let it default
# to the same tokenizer that was used previously for token counting
# NOTE: The tokenizer should be a function that takes in text and returns a list of tokens
token_counter = TokenCountingHandler(
    tokenizer=tiktoken.encoding_for_model("gpt-3.5-turbo").encode,
    verbose=False,  # set to true to see usage printed to the console
)

Settings.callback_manager = CallbackManager([token_counter])

document = SimpleDirectoryReader("./data/test").load_data()

# if verbose is turned on, you will see embedding token usage printed
index = VectorStoreIndex.from_documents(document, embed_model=embed_model)

print(len(list(index.vector_store.data.embedding_dict.values())[0]))
# otherwise, you can access the count directly
print(token_counter.total_embedding_token_count)

# reset the counts at your discretion!
token_counter.reset_counts()

# also track prompt, completion, and total LLM tokens, in addition to embeddings
response = index.as_query_engine().query("What did the author do growing up?")
print(
    "Embedding Tokens: ",
    token_counter.total_embedding_token_count,
    "\n",
    "LLM Prompt Tokens: ",
    token_counter.prompt_llm_token_count,
    "\n",
    "LLM Completion Tokens: ",
    token_counter.completion_llm_token_count,
    "\n",
    "Total LLM Token Count: ",
    token_counter.total_llm_token_count,
)
