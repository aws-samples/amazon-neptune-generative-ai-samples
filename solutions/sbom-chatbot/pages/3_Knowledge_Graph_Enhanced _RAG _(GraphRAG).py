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

        with st.spinner("Executing using Knowledge Graph enhanced RAG..."):
            with st.chat_message("assistant"):
                if index == "Contextual Graph Index":
                    response = (
                        knowledge_graph_enhanced_rag.run_graphrag_answer_question(
                            prompt
                        )
                    )
                elif index == "Vector Index":
                    response = knowledge_graph_enhanced_rag.run_vector_answer_question(
                        prompt
                    )
                elif index == "Hybrid Search":
                    response = knowledge_graph_enhanced_rag.run_hybrid_answer_question(
                        prompt
                    )
                else:
                    response = knowledge_graph_enhanced_rag.run_kgrag_answer_question(
                        prompt
                    )

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
    with st.expander("Triplet Data Model"):
        st.image("images/triplet-data-model.png", use_column_width=True)
    with st.expander("Contextual Data Model"):
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
            "What is an SBOM?",
            "Summarize the information a SaaS provider has to supply me on vulnerabilities and how does that impact my software development process for my SaaS software?",
            "I have a supplier that is not willing to provide me with SBOM data, provide me the reasoning I need to go back to them and discuss why this is a requirement and not an option",
        ),
    )

    index_option = st.radio(
        "Select the type of index to use",
        [
            "Vector Index",
            "Triplet Graph Index",
            "Contextual Graph Index",
        ],
        captions=[
            "Uses Vectors Only",
            "Uses a graph based on subject-predicate-object triplets",
            "Uses a contextual graph of chunks and mentioned entities",
        ],
    )
    st.session_state.index_option = index_option

    if st.button("Try it out", key="graphrag"):
        run_query(kg_option, index_option)
