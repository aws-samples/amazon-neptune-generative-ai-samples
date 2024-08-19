"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

import streamlit as st
from graph import setup_graph


def write_messages(message_state):
    # Display chat messages from history on app rerun
    for message in message_state:
        with st.chat_message(message["role"]):
            create_display(message["content"])


def create_display(response, key=None):
    if isinstance(response, dict) or isinstance(response, list):
        if isinstance(response, dict) and "subgraph" in response:
            setup_graph(response["subgraph"], key=key)
        elif isinstance(response, dict) and "results" in response:
            if isinstance(response["results"], dict) or isinstance(
                response["results"], list
            ):
                st.dataframe(response["results"], use_container_width=True)
            elif "results" in response:
                st.write(response["results"])
            else:
                st.write(response)
        else:
            st.dataframe(response, use_container_width=True)

    else:
        st.write(response)
