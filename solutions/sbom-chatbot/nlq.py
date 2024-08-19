# chain = NeptuneOpenCypherQAChain.from_llm(
#     llm=llm,
#     graph=graph,
#     return_direct=True,
#     return_intermediate_steps=True,
#     extra_instructions="""Wrap all property names in backticks exclude label names.
#                         All comparisons with string values should be done in lowercase.
#                         Do not use RegexMatch queries, use a lowercase CONTAINS search instead.
#                         If you don't know how to write a query given the prompt return 'I don't know' """,
# )

# chat = ChatBedrock(
#     model_id="anthropic.claude-3-sonnet-20240229-v1:0",
#     model_kwargs={"temperature": 0.1},
# )
