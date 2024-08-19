"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

import streamlit as st
from llm import run_graphrag_answer_question
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


def run_query(prompt):
    messages.append({"role": "user", "content": prompt})

    with tab1:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner("Executing using Knowledge Graph enhanced RAG..."):
            with st.chat_message("assistant"):
                response = run_graphrag_answer_question(prompt)
                create_display(response["results"])
                with st.popover("Quotes"):
                    st.code(response["quotes"])
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
tab1, tab2 = st.tabs(["Chat", "Architecture"])
with tab1:
    # Setup the chat input
    write_messages(messages)

with tab2:
    st.image("GraphRAG_Questions.png", use_column_width=True)

    st.image("graph.png", use_column_width=True)

# React to user input
if prompt := st.chat_input():
    run_query(prompt)

# Configure the sidebar with the example questions
with st.sidebar:
    st.header("Example Queries")

    kg_option = st.selectbox(
        "Select a Knowledge Graph Query to run:",
        (
            "What is an SBOM and what are the top reasons why we should use them?",
            "What are the recommended best practices for storing SBOM data?",
        ),
    )

    if st.button("Try it out", key="graphrag"):
        run_query(kg_option)
