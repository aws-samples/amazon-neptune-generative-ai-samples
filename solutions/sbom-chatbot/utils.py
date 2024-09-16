"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from typing import List
from DisplayResult import DisplayResult
import streamlit as st
from st_link_analysis import st_link_analysis, NodeStyle, EdgeStyle
import uuid


def write_messages(message_state: List[dict]) -> None:
    """Display chat messages from history on app rerun

    Args:
        message_state (List[dict]): The message state
    """
    for message in message_state:
        with st.chat_message(message["role"]):
            create_display(message["content"])


def create_display(result: object) -> None:
    """Creates the display feature for the given input (string or DisplayResult)

    Args:
        result (object): The input to display
    """
    if isinstance(result, str):
        st.write(result)
    else:
        response = result.results
        if result.display_format.value == DisplayResult.DisplayFormat.SUBGRAPH.value:
            setup_graph(response)
        elif result.display_format.value == DisplayResult.DisplayFormat.STRING.value:
            if result.status.value == DisplayResult.Status.SUCCESS.value:
                st.info(response)
            else:
                st.error(response)
        elif result.display_format.value == DisplayResult.DisplayFormat.TABLE.value:
            st.dataframe(response, use_container_width=True)
        elif result.display_format.value == DisplayResult.DisplayFormat.JSON.value:
            st.json(response)
        else:
            if isinstance(response, dict) or isinstance(response, list):
                st.dataframe(response, use_container_width=True)
            else:
                if result.status.value == DisplayResult.Status.SUCCESS.value:
                    st.info(response)
                else:
                    st.error(response)


def get_color(label: str) -> str:
    """Returns the display color for the label

    Args:
        label (str): The label

    Returns:
        str: The display color
    """
    match label:
        case "Vulnerability":
            return "red"
        case "Component":
            return "yellow"
        case "Document":
            return "blue"
        case "License":
            return "orange"
        case _:
            return "grey"


def get_id(label: str, n: dict) -> str:
    """Returns the appropriate display text

    Args:
        label (str): The label
        n (dict): The node

    Returns:
        str: The display text
    """
    match label:
        case "Vulnerability":
            return f"Vulnerability: {n['~properties']['id']}"
        case _:
            return n["~id"]


def setup_graph(data: List) -> cytoscape:
    """Creates a Cytoscape graph given a set of nodes and edges

    Args:
        data (List): The nodes and edges

    Returns:
        st_link_analysis: A custom Streamlit component for link analysis, built with Cytoscape.js 
    """
    elements = {}
    nodes_list = []
    edges_list = []
    for d in data:
        if "nodes" in d["res"] and not d["res"]["nodes"] is None:
            for n in d["res"]["nodes"]:
                id = n["~id"]
                nodes_list.append(
                    {
                        "data": {
                            "id": n["~id"],
                            "label": n["~labels"][0],
                        }
                    }
                )

        if "edges" in d["res"] and not d["res"]["edges"] is None:
            for e in d["res"]["edges"]:
                elements.append(
                    {
                        "data": {
                            "id": e["~id"],
                            "source": e["~start"],
                            "target": e["~end"],
                            "label": e["~type"],
                        }
                    }
                )
    elements['nodes'] = nodes_list
    elements['edges'] = edges_list
    key = str(uuid.uuid4())

    node_styles = [
        NodeStyle("Entity", "#7e3eff", "label", "person"),
        NodeStyle("Reference", "#ff4d3e", "label", "link"),
        NodeStyle("License", "#508f2c", "label", "credit_card"),
        NodeStyle("Vulnerability", "#f8a138", "label", "lock"),
        NodeStyle("Component", "#2A629A", "label", "description"),
        NodeStyle("Chunk", "#2A629A", "label", "description"),
        NodeStyle("Document", "#2A629A", "label", "description"),
        NodeStyle("Fact", "#2A629A", "label", "description"),
        NodeStyle("Source", "#2A629A", "label", "description"),
    ]

    edge_styles = [
        EdgeStyle("RELATION", labeled=True, directed=True),
        EdgeStyle("LICENSED_BY", labeled=True, directed=True),
        EdgeStyle("DESCRIBES", labeled=True, directed=True),
        EdgeStyle("NEXT", labeled=True, directed=True),
        EdgeStyle("SOURCE", labeled=True, directed=True),
        EdgeStyle("DEPENDS_ON", labeled=True, directed=True),
        EdgeStyle("SUBJECT", labeled=True, directed=True),
        EdgeStyle("OBJECT", labeled=True, directed=True),
        EdgeStyle("AFFECTS", labeled=True, directed=True),
        EdgeStyle("REFERS_TO", labeled=True, directed=True),
    ]

    if len(elements) > 0:
        return st_link_analysis(
            elements, node_styles=node_styles, edge_styles=edge_styles, layout="cose", key=key
        )
    else:
        return st.write(
            "The question returned no answers.  Please try again with a different question/combination."
        )
