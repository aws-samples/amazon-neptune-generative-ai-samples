"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from typing import List
from DisplayResult import DisplayResult
import streamlit as st
from st_cytoscape import cytoscape


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
        cytoscape: A cytoscape graph
    """
    elements = []
    for d in data:
        if "nodes" in d["res"] and not d["res"]["nodes"] is None:
            for n in d["res"]["nodes"]:
                color = get_color(n["~labels"][0])
                id = get_id(n["~labels"][0], n)
                elements.append(
                    {
                        "data": {
                            "id": n["~id"],
                            "label": id,
                            "color": color,
                        }
                    }
                )

        if "edges" in d["res"] and not d["res"]["edges"] is None:
            for e in d["res"]["edges"]:
                elements.append(
                    {
                        "data": {
                            "source": e["~start"],
                            "target": e["~end"],
                            "label": e["~type"],
                        }
                    }
                )
    stylesheet = [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "width": 20,
                "height": 20,
                "background-color": "data(color)",
            },
        },
        {
            "selector": "edge",
            "style": {
                "label": "data(label)",
                "width": 3,
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
            },
        },
    ]
    layout = {
        "name": "fcose",
        "animationDuration": 0,
        "padding": 50,
        "nodeDimensionsIncludeLabels": True,
        "nodeRepulsion": 4096,
        "fit": True,
    }
    if len(elements) > 0:
        return cytoscape(
            elements, stylesheet, layout=layout, selection_type="single", height="400px"
        )
    else:
        return st.write(
            "The question returned no answers.  Please try again with a different question/combination."
        )
