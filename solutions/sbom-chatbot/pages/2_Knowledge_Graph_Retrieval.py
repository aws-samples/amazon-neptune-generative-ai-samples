"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import streamlit as st
import pandas as pd
from llm import run_templated_query, get_vulnerability_list, QUERY_TYPES
from utils import write_messages, create_display

# ------------------------------------------------------------------------
# Functions
# This section contains the functions needed to be called by our streamlit app


# # Store LLM generated responses
if "messages_byokg" not in st.session_state.keys():
    st.session_state.messages_byokg = [
        {
            "role": "assistant",
            "content": "How may I assist you today?",
            "context": "assistant",
        }
    ]

messages = st.session_state.messages_byokg


def run_query(prompt, type):
    st.session_state.messages_byokg.append({"role": "user", "content": prompt})

    with tab1:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner(f"Executing using graph retrieval queries ..."):
            with st.chat_message("assistant"):
                response = run_templated_query(prompt, type)
                create_display(response, key=sim_option)
                st.session_state.messages_byokg.append(
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

st.title("Query an Existing Knowledge Graph")
st.write(
    """Using Amazon Bedrock Foundation models, your natural language question will have the key entities extracted, 
    which are then be run using templated queries, and results returned."""
)

# Setup columns for the two chatbots
tab1, tab2 = st.tabs(["Chat", "Architecture"])
with tab1:
    # Setup the chat input
    write_messages(messages)

with tab2:
    st.image("Templated_Questions.png", use_column_width=True)


# React to user input
if prompt := st.chat_input():
    run_query(prompt)

# Configure the sidebar with the example questions
with st.sidebar:
    st.header("Example Queries")

    sim_option = st.selectbox("Select a Vulnerability:", get_vulnerability_list())

    if st.button("Find the most similar", key="sim_queries"):
        run_query(
            f"What Vulnerabilities are similar to '{sim_option}'?",
            QUERY_TYPES.Templated,
        )
    if st.button("Show me how they are connected", key="whole_dataset"):
        run_query(
            f"What Vulnerabilities are similar to '{sim_option}' and show me how they are connected",
            QUERY_TYPES.Explainability,
        )
