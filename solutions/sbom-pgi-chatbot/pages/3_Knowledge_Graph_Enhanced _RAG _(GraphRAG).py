"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import streamlit as st
from llm import knowledge_graph_enhanced_rag
from utils import write_messages, create_display

# ------------------------------------------------------------------------
# Functions
# This section contains the functions needed to be called by our streamlit app


# # Store LLM generated responses
if "messages_grag" not in st.session_state.keys():
    st.session_state.messages_grag = [
        {
            "role": "assistant",
            "content": "How may I assist you today?",
            "context": "assistant",
        }
    ]


messages = st.session_state.messages_grag


def run_query(prompt, index):
    messages.append({"role": "user", "content": prompt})

    with tab1:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner(f"Executing using Knowledge Graph enhanced RAG using {index}"):
            with st.chat_message("assistant"):
                if index == "RAG (Vector Index)":
                    response = knowledge_graph_enhanced_rag.run_vector_answer_question(
                        prompt
                    )
                else:
                    response = (
                        knowledge_graph_enhanced_rag.run_graphrag_answer_question(
                            prompt
                        )
                    )
                if response.results:
                    response.results += f"\n\n {index}"
                create_display(response)
                with st.popover("Evidence"):
                    st.write(response.explaination)
                messages.append(
                    {"role": "assistant", "content": response, "type": "table"}
                )


# ------------------------------------------------------------------------
# Streamlit
# This section represents our Streamlit App UI and Actions

# Page title
st.set_page_config(
    page_title="Neptune Generative AI Demo",
    page_icon="🔱",
    layout="wide",
)

st.title("Knowledge Graph Enhanced RAG")
st.write(
    """Using Amazon Bedrock Foundation models, your natural language question will be answered using a combination of
    Knowledge Graph queries and Vector similarity.  This data will then be sent to the LLM for summarization and 
    results returned."""
)

# Setup columns for the two chatbots
tab1, tab2, tab3 = st.tabs(["Chat", "Architecture", "Data Model"])
with tab1:
    # Setup the chat input
    write_messages(messages)

with tab2:
    indexing, retrieval = st.tabs(["Indexing", "Retrieval"])
    with indexing:
        with st.expander("RAG Indexing"):
            st.image("images/rag-indexing.png", use_column_width=True)

        with st.expander("GraphRAG Indexing"):
            st.image("images/graphrag-indexing.png", use_column_width=True)
    with retrieval:
        with st.expander("RAG Retrieval"):
            st.image("images/rag-retrieval.png", use_column_width=True)
        with st.expander("GraphRAG Retrieval"):
            st.image("images/graphrag-retrieval.png", use_column_width=True)

with tab3:
    st.subheader("Graph Data Model")
    st.image("images/contextual-data-model.png", use_column_width=True)

# React to user input
if prompt := st.chat_input():
    run_query(prompt, st.session_state.index_option)

# Configure the sidebar with the example questions
with st.sidebar:
    st.header("Example Queries")

    kg_option = st.selectbox(
        "Select a Knowledge Graph Query to run:",
        (
            "My vendor isn't giving me an SBOM, what do I do now?",
            """
            I am adding a new software release to our deployment pipeline which is collecting SBOMs. Once I have an SBOM where do I store it?
            """,
            """
            My application uses a managed service, what are my requirements around having SBOM data for applications using this service?
            """,
        ),
    )

    index_option = st.radio(
        "Select the type of retrieval to use",
        ["RAG (Vector Index)", "GraphRAG (Graph Index)"],
        captions=[
            "Uses Vectors Only",
            "Uses a graph based on subject-predicate-object triplets",
        ],
    )
    st.session_state.index_option = index_option

    if st.button("Try it out", key="graphrag"):
        run_query(kg_option, index_option)
