"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import streamlit as st
from llm import defined_domain_qa
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

    with chatbot_container:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner(f"Executing using graph retrieval queries ..."):
            with st.chat_message("assistant"):
                response = defined_domain_qa.run_retrieval_query(prompt)
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

st.title("Defined Domain Question Answering")
st.write(
    """Using Amazon Bedrock Foundation models, your natural language 
    question will be reviewed to determine the intent, then the 
    key entities are extracted, a templated openCypher query is executed, and results returned."""
)

chatbot_container = st.container()
with chatbot_container:
    # Setup the chat input
    write_messages(messages)

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
        ),
    )

    sim_option = st.selectbox(
        "Select a Library (Component):",
        ["libssl3", "openldap", "openjdk11-jre", "yum", "python", "rpm"],
    )

    if st.button("Try it out", key="kg_queries"):
        run_query(kg_option.replace("_____", sim_option))
