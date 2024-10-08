"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import streamlit as st
from llm import open_domain_qa
from utils import write_messages, create_display

# Store LLM generated responses
if "messages_nlq" not in st.session_state.keys():
    st.session_state.messages_nlq = [
        {
            "role": "assistant",
            "content": "How may I assist you today?",
            "context": "assistant",
        }
    ]

messages = st.session_state.messages_nlq


if "summarize" not in st.session_state:
    st.session_state.summarize = False


def change_summarize():
    st.session_state.summarize = False if st.session_state.summarize else True


def run_query(prompt: str):
    messages.append({"role": "user", "content": prompt})

    with chatbot_container:
        with st.chat_message("user"):
            st.write(prompt)

        with st.spinner(f"Executing using natural language query translation ..."):
            with st.chat_message("assistant"):
                response = open_domain_qa.run_natural_language_query(
                    prompt, st.session_state.summarize
                )
                create_display(response)
                with st.popover("Query"):
                    st.code(response.explanation)
                messages.append(
                    {"role": "assistant", "content": response, "type": "table"}
                )


st.set_page_config(
    page_title="Neptune Generative AI Demo",
    page_icon="🔱",
    layout="wide",
)

st.title("Open Domain Question Answering")
st.write(
    """Using Amazon Bedrock Foundation models, your natural language 
    question will be converted into an openCypher query,
    which will then be run, and results returned."""
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
        "Select the query to run or enter your own below:",
        (
            "How many Vulnerabilities exist?",
            """Find me the components that have 'high' or 'critical' vulnerabilities?  Return the component and number of vulnerabilities grouped by severity. 
Group by component and severity count, order by component then by severity""",
            "Delete all data in the database    ",
        ),
    )

    summarize = st.toggle("Summarize Response", value=False, on_change=change_summarize)

    if st.button("Try it out", key="kg_queries"):
        run_query(kg_option.replace("/n", ""))
