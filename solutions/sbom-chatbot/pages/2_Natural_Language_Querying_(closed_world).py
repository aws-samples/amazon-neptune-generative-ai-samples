"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import streamlit as st
import pandas as pd
from llm import knowledge_graph_retreiver
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


def run_query(prompt):
    st.session_state.messages_byokg.append({"role": "user", "content": prompt})

    with tab1:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner(f"Executing using graph retrieval queries ..."):
            with st.chat_message("assistant"):
                response = knowledge_graph_retreiver.run_retrieval_query(prompt)
                create_display(response)
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

st.title("Natural Language Query (Closed World)")
st.write("""Using Amazon Bedrock Foundation models, intent and key entities are extracted from natural language questions, which are then used to run templated queries.""")

# Setup columns for the two chatbots
tab1, tab2, tab3 = st.tabs(["Chat", "Architecture", "Data Model"])
with tab1:
    # Setup the chat input
    write_messages(messages)

with tab2:
    st.image("images/nlq-closed-world.png", use_column_width=True)

with tab3:
    st.image("images/schema.png", use_column_width=True)

# React to user input
if prompt := st.chat_input():
    run_query(prompt)

# Configure the sidebar with the example questions
with st.sidebar:
    st.header("Example Queries")

    kg_option = st.selectbox(
        "Select the question to ask:",
        (
            f"Find me information about _____",
            f"Find me documents and vulnerabilities associated with _____",
            f"Find me all the documents that share component _____ and their vulnerabilties",
            "Delete all data in the database",
        ),
    )

    sim_option = st.selectbox(
        "Select a Library (Component):", ["libssl3", "openldap", "openjdk11-jre", "yum"]
    )

    if st.button("Try it out", key="kg_queries"):
        run_query(kg_option.replace("_____", sim_option))
